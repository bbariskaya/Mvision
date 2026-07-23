import asyncio
import logging
import math
import secrets
import time
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import (
    LiveCameraRun,
    LiveSessionGeneration,
    LiveSessionRun,
)
from app.infrastructure.database.repositories import (
    LiveCameraRepository,
    LiveRunRepository,
    LiveSessionRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.live.native_runner import (
    LiveCommandQueue,
    NativeLiveRunner,
    NativeLiveRunnerError,
)
from app.infrastructure.live.protocol import (
    PROTOCOL_VERSION,
    FailedEvent,
    LiveMessage,
    MetricsEvent,
    NativeOperationEvent,
    ProtocolHeader,
    StartCommand,
    StateEvent,
    StopCommand,
    TrackEvidenceEvent,
    TrackExpiredEvent,
)
from app.infrastructure.live.uri_cipher import LiveUriCipher, redact_live_text
from app.observability.metrics import MvisionMetrics
from app.observability.semantic import native_span_name
from app.observability.telemetry import TelemetryRuntime

logger = logging.getLogger(__name__)


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class LiveLeaseLostError(RuntimeError):
    pass


class LiveSupervisor:
    def __init__(
        self,
        settings: Settings,
        cameras: LiveCameraRepository,
        runs: LiveRunRepository,
        cipher: LiveUriCipher | None,
        runner: NativeLiveRunner,
        *,
        identity_service: Any | None = None,
        event_service: Any | None = None,
        telemetry: TelemetryRuntime | None = None,
        metrics: MvisionMetrics | None = None,
        session_repository: LiveSessionRepository | None = None,
        session_factory: SessionFactory = AsyncSessionLocal,
        monitor_interval_seconds: float | None = None,
    ):
        self._settings = settings
        self._cameras = cameras
        self._runs = runs
        self._cipher = cipher
        self._runner = runner
        self._identity_service = identity_service
        self._event_service = event_service
        self._telemetry = telemetry or TelemetryRuntime(enabled=False)
        self._metrics = metrics
        self._session_runs = session_repository or LiveSessionRepository()
        self._session_factory = session_factory
        self._monitor_interval = monitor_interval_seconds or max(
            1.0, settings.live_worker_lease_seconds / 3
        )
        self._active_commands: LiveCommandQueue | None = None
        self._active_header: ProtocolHeader | None = None
        self._command_sequence = 2
        self._metric_counters: dict[tuple[str, str], int] = {}

    async def process_one_camera(self, worker_id: str) -> bool:
        claim_started_ns = time.time_ns()
        lease_token = new_uuid7()
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            run = await self._runs.claim(
                session,
                camera_id=None,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now,
                lease_seconds=self._settings.live_worker_lease_seconds,
            )
            camera = await self._cameras.get(session, run.camera_id) if run is not None else None
            await session.commit()
        if run is None:
            return False
        if camera is None or self._cipher is None:
            await self._finish_failed(
                run, worker_id, lease_token, "LIVE_SECRET_CONFIGURATION_REQUIRED"
            )
            return True

        plaintext_uri: str | None = None
        start: StartCommand | None = None
        commands = LiveCommandQueue(self._settings.live_assignment_queue_capacity)
        failed_event: FailedEvent | None = None
        lease_lost = False
        runner_task: asyncio.Task | None = None
        monitor_task: asyncio.Task | None = None
        identity_task: asyncio.Task | None = None
        identity_queue: asyncio.Queue[TrackEvidenceEvent | TrackExpiredEvent] | None = None
        parent_context = self._telemetry.context_from_headers(run.traceparent, run.tracestate)
        with self._telemetry.start_span(
            "live.supervisor.claim",
            {
                "camera_id": run.camera_id,
                "run_id": run.run_id,
                "generation": run.generation,
            },
            context=parent_context,
            start_time=claim_started_ns,
        ) as claim_span:
            run_context = trace.set_span_in_context(claim_span)
        run_scope = self._telemetry.start_span(
            "live.camera.run",
            {
                "camera_id": run.camera_id,
                "run_id": run.run_id,
                "generation": run.generation,
            },
            context=run_context,
        )
        run_span = run_scope.__enter__()
        anchor_wall_ns = time.time_ns()
        anchor_monotonic_ns = time.monotonic_ns()
        try:
            plaintext_uri = self._cipher.decrypt(camera.uri_ciphertext).get_secret_value()
            start = self._start_command(run, plaintext_uri)
            self._active_commands = commands
            self._active_header = start.header
            if self._identity_service is not None and self._event_service is not None:
                identity_queue = asyncio.Queue(
                    maxsize=self._settings.live_identity_work_queue_capacity
                )
                identity_task = asyncio.create_task(
                    self._process_identity_events(identity_queue, commands)
                )

            async def on_event(event: LiveMessage) -> None:
                nonlocal failed_event
                if isinstance(event, FailedEvent):
                    failed_event = event
                    return
                if isinstance(event, StateEvent):
                    if event.state in {"STOPPED", "FAILED"}:
                        return
                    await self._persist_state(run, worker_id, lease_token, event)
                elif isinstance(event, MetricsEvent):
                    await self._persist_metrics(run, worker_id, lease_token, event)
                elif isinstance(event, NativeOperationEvent):
                    self._record_native_operation(event, anchor_wall_ns, anchor_monotonic_ns)
                elif isinstance(event, (TrackEvidenceEvent, TrackExpiredEvent)):
                    if identity_queue is not None:
                        try:
                            identity_queue.put_nowait(event)
                        except asyncio.QueueFull:
                            logger.warning("Live identity work queue full; event dropped")

            runner_task = asyncio.create_task(self._runner.run(start, on_event, commands))
            monitor_task = asyncio.create_task(self._monitor(run, worker_id, lease_token, commands))
            done, _ = await asyncio.wait(
                {runner_task, monitor_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if monitor_task in done:
                monitor_error = monitor_task.exception()
                if isinstance(monitor_error, LiveLeaseLostError):
                    lease_lost = True
                    runner_task.cancel()
                    await asyncio.gather(runner_task, return_exceptions=True)
                    return True
                if monitor_error is not None:
                    raise monitor_error
            await runner_task
            if identity_queue is not None:
                await identity_queue.join()
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            if failed_event is not None:
                await self._finish(
                    run,
                    worker_id,
                    lease_token,
                    "FAILED",
                    failed_event.error_code,
                    failed_event.message,
                )
            else:
                await self._finish(run, worker_id, lease_token, "STOPPED")
            return True
        except LiveLeaseLostError:
            lease_lost = True
            return True
        except Exception as exc:
            error_code = (
                exc.error_code if isinstance(exc, NativeLiveRunnerError) else "LIVE_PIPELINE_ERROR"
            )
            run_span.set_attribute("error_code", error_code)
            run_span.set_status(Status(StatusCode.ERROR, error_code))
            if not lease_lost:
                await self._finish(run, worker_id, lease_token, "FAILED", error_code, str(exc))
            return True
        finally:
            for task in (runner_task, monitor_task, identity_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (runner_task, monitor_task, identity_task) if task is not None),
                return_exceptions=True,
            )
            self._active_commands = None
            self._active_header = None
            plaintext_uri = None
            start = None
            run_scope.__exit__(None, None, None)

    async def process_one_session(self, worker_id: str) -> bool:
        claim_started_ns = time.time_ns()
        lease_token = new_uuid7()
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            run = await self._session_runs.claim_generation(
                session,
                worker_id,
                lease_token,
                now,
                lease_seconds=self._settings.live_worker_lease_seconds,
            )
            generation = (
                await self._session_runs.get_generation(session, run.generation_id)
                if run is not None
                else None
            )
            await session.commit()
        if run is None:
            return False
        if generation is None:
            await self._finish_session(
                run,
                worker_id,
                lease_token,
                "FAILED",
                "LIVE_SESSION_GENERATION_NOT_FOUND",
            )
            return True

        commands = LiveCommandQueue(self._settings.live_assignment_queue_capacity)
        failed_event: FailedEvent | None = None
        lease_lost = False
        runner_task: asyncio.Task | None = None
        monitor_task: asyncio.Task | None = None
        with self._telemetry.start_span(
            "live.supervisor.claim",
            {
                "session_id": generation.session_id,
                "run_id": run.run_id,
                "generation": generation.generation,
                "runtime_attempt": run.runtime_attempt,
            },
            start_time=claim_started_ns,
        ) as claim_span:
            run_context = trace.set_span_in_context(claim_span)
        run_scope = self._telemetry.start_span(
            "live.session.run",
            {
                "session_id": generation.session_id,
                "run_id": run.run_id,
                "generation": generation.generation,
                "runtime_attempt": run.runtime_attempt,
            },
            context=run_context,
        )
        run_span = run_scope.__enter__()
        anchor_wall_ns = time.time_ns()
        anchor_monotonic_ns = time.monotonic_ns()
        try:
            active_start = self._session_start_command(run, generation)
            self._active_commands = commands
            self._active_header = active_start.header

            async def on_event(event: LiveMessage) -> None:
                nonlocal failed_event
                self._require_matching_header(active_start.header, event.header)
                if isinstance(event, FailedEvent):
                    failed_event = event
                    return
                if isinstance(event, StateEvent):
                    if event.state in {"STOPPED", "FAILED"}:
                        return
                    await self._persist_session_state(run, worker_id, lease_token, event)
                elif isinstance(event, NativeOperationEvent):
                    self._record_native_operation(event, anchor_wall_ns, anchor_monotonic_ns)

            runner_task = asyncio.create_task(self._runner.run(active_start, on_event, commands))
            monitor_task = asyncio.create_task(
                self._monitor_session(run, generation, worker_id, lease_token, commands)
            )
            done, _ = await asyncio.wait(
                {runner_task, monitor_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if monitor_task in done:
                monitor_error = monitor_task.exception()
                if isinstance(monitor_error, LiveLeaseLostError):
                    lease_lost = True
                    runner_task.cancel()
                    await asyncio.gather(runner_task, return_exceptions=True)
                    return True
                if monitor_error is not None:
                    raise monitor_error
            await runner_task
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            if failed_event is not None:
                await self._finish_session(
                    run,
                    worker_id,
                    lease_token,
                    "FAILED",
                    failed_event.error_code,
                )
            else:
                await self._finish_session(run, worker_id, lease_token, "STOPPED")
            return True
        except LiveLeaseLostError:
            lease_lost = True
            return True
        except Exception as exc:
            error_code = (
                exc.error_code if isinstance(exc, NativeLiveRunnerError) else "LIVE_PIPELINE_ERROR"
            )
            run_span.set_attribute("error_code", error_code)
            run_span.set_status(Status(StatusCode.ERROR, error_code))
            if not lease_lost:
                try:
                    await self._finish_session(
                        run,
                        worker_id,
                        lease_token,
                        "FAILED",
                        error_code,
                    )
                except LiveLeaseLostError:
                    lease_lost = True
            return True
        finally:
            for task in (runner_task, monitor_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (runner_task, monitor_task) if task is not None),
                return_exceptions=True,
            )
            self._active_commands = None
            self._active_header = None
            run_scope.__exit__(None, None, None)

    def _record_native_operation(
        self,
        event: NativeOperationEvent,
        anchor_wall_ns: int,
        anchor_monotonic_ns: int,
    ) -> None:
        started_ns = anchor_wall_ns + event.started_monotonic_ns - anchor_monotonic_ns
        ended_ns = anchor_wall_ns + event.ended_monotonic_ns - anchor_monotonic_ns
        if started_ns <= 0 or abs(event.started_monotonic_ns - anchor_monotonic_ns) > 86_400e9:
            logger.warning("Native operation timestamp outside run boundary; event dropped")
            return
        self._telemetry.record_span(
            native_span_name(event.operation),
            start_time=started_ns,
            end_time=ended_ns,
            attributes={
                "operation": event.operation,
                "status": event.status,
                **event.attributes,
            },
            error_code=event.error_code,
        )
        if self._metrics is not None:
            self._metrics.observe(
                "native_operation_duration_seconds",
                (event.ended_monotonic_ns - event.started_monotonic_ns) / 1_000_000_000,
                operation=event.operation,
                status="success" if event.status == "ok" else "error",
            )

    async def _process_identity_events(
        self,
        queue: asyncio.Queue[TrackEvidenceEvent | TrackExpiredEvent],
        commands: LiveCommandQueue,
    ) -> None:
        identity_service = self._identity_service
        event_service = self._event_service
        assert identity_service is not None and event_service is not None
        while True:
            event = await queue.get()
            try:
                if isinstance(event, TrackEvidenceEvent):
                    decision = await identity_service.resolve(event)
                    assignments = await event_service.accept_decision(
                        event.header.camera_id,
                        event.header.run_id,
                        event.header.generation,
                        event,
                        decision,
                    )
                else:
                    assignments = await event_service.expire_track(
                        event.header.camera_id,
                        event.header.run_id,
                        event.header.generation,
                        event,
                    )
                    identity_service.expire(event)
                for assignment in assignments:
                    commands.put_nowait(assignment)
            except Exception:
                logger.error("Live identity event processing failed")
            finally:
                queue.task_done()

    def request_stop(self, reason: str = "worker_shutdown") -> None:
        if self._active_commands is None:
            return
        self._active_commands.put_nowait(self._stop_command(reason))

    def _session_start_command(
        self, run: LiveSessionRun, generation: LiveSessionGeneration
    ) -> StartCommand:
        resolved = generation.resolved_spec
        if not isinstance(resolved, dict):
            raise ValueError("LIVE_RESOLVED_SPEC_INVALID")

        def section(name: str) -> dict[str, Any]:
            value = resolved.get(name)
            if not isinstance(value, dict):
                raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
            return value

        def integer(values: dict[str, Any], name: str, *, minimum: int = 0) -> int:
            value = values.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
            return value

        def probability(values: dict[str, Any], name: str) -> float:
            value = values.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
            result = float(value)
            if not math.isfinite(result) or not 0.0 <= result <= 1.0:
                raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
            return result

        def flag(values: dict[str, Any], name: str) -> bool:
            value = values.get(name)
            if not isinstance(value, bool):
                raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
            return value

        processing = section("processing")
        source_policy = section("source_policy")
        recording = section("recording")
        annotated_stream = section("annotated_stream")
        analytics_mode = processing.get("mode")
        if analytics_mode not in {"detect", "detectTrack", "recognize"}:
            raise ValueError("LIVE_RESOLVED_SPEC_INVALID")
        sampling_value = processing.get("sampling_value")
        if (
            processing.get("sampling_mode") != "everyNFrames"
            or isinstance(sampling_value, bool)
            or not isinstance(sampling_value, (int, float))
            or not math.isfinite(float(sampling_value))
            or float(sampling_value) < 1
            or not float(sampling_value).is_integer()
        ):
            raise ValueError("LIVE_SAMPLING_MODE_UNSUPPORTED")
        sample_every_n = int(sampling_value)
        latency_ms = integer(source_policy, "latency_ms")
        frame_timeout_ms = integer(source_policy, "frame_timeout_ms", minimum=1)
        reconnect_interval_ms = integer(source_policy, "reconnect_interval_ms", minimum=1)
        reconnect_attempts = integer(source_policy, "reconnect_attempts", minimum=-1)
        track_gap_ms = integer(processing, "track_gap_ms", minimum=1)
        if (
            isinstance(generation.profile_version, bool)
            or not isinstance(generation.profile_version, int)
            or generation.profile_version < 1
        ):
            raise ValueError("LIVE_RESOLVED_SPEC_INVALID")

        origin = self._settings.mediamtx_internal_rtsp_origin.rstrip("/")
        ingress_path = generation.ingress_path.strip("/")
        if (
            not origin.startswith(("rtsp://", "rtsps://"))
            or any(ord(character) < 0x20 for character in origin)
            or not ingress_path.startswith("ingress/")
            or any(segment in {"", ".", ".."} for segment in ingress_path.split("/"))
            or any(ord(character) < 0x20 for character in ingress_path)
        ):
            raise ValueError("LIVE_INTERNAL_MEDIA_PATH_INVALID")

        traceparent = f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
        header = ProtocolHeader(
            protocol_version=PROTOCOL_VERSION,
            message_type="start",
            session_id=generation.session_id,
            camera_id=generation.session_id,
            run_id=run.run_id,
            generation=generation.generation,
            runtime_attempt=run.runtime_attempt,
            sequence=1,
            traceparent=traceparent,
            tracestate=None,
        )
        return StartCommand(
            header=header,
            uri=f"{origin}/{ingress_path}",
            gpu_id=self._settings.live_worker_gpu_id,
            pgie_config_path=self._settings.live_pgie_config_path,
            preprocess_config_path=self._settings.live_preprocess_config_path,
            sgie_config_path=self._settings.live_sgie_config_path,
            tracker_config_path=self._settings.live_tracker_config_path,
            output_mount_path=f"/live/{generation.session_id}",
            output_udp_port=self._settings.live_rtp_udp_port,
            output_rtsp_port=self._settings.live_rtsp_output_port,
            profile_version=generation.profile_version,
            analytics_mode=analytics_mode,
            sample_every_n=sample_every_n,
            detector_threshold=probability(processing, "detector_threshold"),
            recognition_threshold=probability(processing, "recognition_threshold"),
            top2_margin=probability(processing, "top2_margin"),
            track_gap_ns=track_gap_ms * 1_000_000,
            latency_ms=latency_ms,
            reconnect_interval_seconds=max(1, math.ceil(reconnect_interval_ms / 1_000)),
            reconnect_attempts=reconnect_attempts,
            frame_timeout_ns=frame_timeout_ms * 1_000_000,
            recording_enabled=flag(recording, "enabled"),
            annotated_enabled=flag(annotated_stream, "enabled"),
        )

    @staticmethod
    def _require_matching_header(expected: ProtocolHeader, received: ProtocolHeader) -> None:
        checks = (
            (received.session_id == expected.session_id, "WRONG_SESSION_ID"),
            (received.camera_id == expected.camera_id, "WRONG_CAMERA_ID"),
            (received.run_id == expected.run_id, "WRONG_RUN_ID"),
            (received.generation == expected.generation, "WRONG_GENERATION"),
            (
                received.runtime_attempt == expected.runtime_attempt,
                "WRONG_RUNTIME_ATTEMPT",
            ),
        )
        for matches, code in checks:
            if not matches:
                raise LiveLeaseLostError(code)

    async def _monitor_session(
        self,
        run: LiveSessionRun,
        generation: LiveSessionGeneration,
        worker_id: str,
        lease_token: str,
        commands: LiveCommandQueue,
    ) -> None:
        stop_sent = False
        while True:
            await asyncio.sleep(self._monitor_interval)
            now = datetime.now(UTC)
            with self._telemetry.start_span(
                "live.supervisor.lease_renew",
                {
                    "session_id": generation.session_id,
                    "run_id": run.run_id,
                    "generation": generation.generation,
                    "runtime_attempt": run.runtime_attempt,
                },
            ):
                async with self._session_factory() as session:
                    current = await self._session_runs.get_generation(session, run.generation_id)
                    renewed = await self._session_runs.renew_run(
                        session,
                        run.run_id,
                        worker_id,
                        lease_token,
                        now,
                        now + timedelta(seconds=self._settings.live_worker_lease_seconds),
                        generation_id=run.generation_id,
                        runtime_attempt=run.runtime_attempt,
                    )
                    await session.commit()
            if not renewed:
                raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")
            if (current is None or current.desired_state != "running") and not stop_sent:
                commands.put_nowait(self._stop_command("desired_stopped"))
                stop_sent = True

    async def _persist_session_state(
        self,
        run: LiveSessionRun,
        worker_id: str,
        lease_token: str,
        event: StateEvent,
    ) -> None:
        async with self._session_factory() as session:
            updated = await self._session_runs.update_run_state(
                session,
                run.run_id,
                worker_id,
                lease_token,
                datetime.now(UTC),
                generation_id=run.generation_id,
                runtime_attempt=run.runtime_attempt,
                runtime_state=event.state,
            )
            await session.commit()
        if not updated:
            raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")

    async def _finish_session(
        self,
        run: LiveSessionRun,
        worker_id: str,
        lease_token: str,
        runtime_state: str,
        error_code: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            updated = await self._session_runs.finish_run(
                session,
                run.run_id,
                worker_id,
                lease_token,
                datetime.now(UTC),
                generation_id=run.generation_id,
                runtime_attempt=run.runtime_attempt,
                runtime_state=runtime_state,
                error_code=error_code,
            )
            await session.commit()
        if not updated:
            raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")

    async def _monitor(
        self,
        run: LiveCameraRun,
        worker_id: str,
        lease_token: str,
        commands: LiveCommandQueue,
    ) -> None:
        stop_sent = False
        while True:
            await asyncio.sleep(self._monitor_interval)
            now = datetime.now(UTC)
            with self._telemetry.start_span(
                "live.supervisor.lease_renew",
                {
                    "camera_id": run.camera_id,
                    "run_id": run.run_id,
                    "generation": run.generation,
                },
            ):
                async with self._session_factory() as session:
                    camera = await self._cameras.get(session, run.camera_id)
                    renewed = await self._runs.renew(
                        session,
                        run.run_id,
                        worker_id,
                        lease_token,
                        now,
                        now + timedelta(seconds=self._settings.live_worker_lease_seconds),
                    )
                    await session.commit()
            if not renewed:
                raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")
            if (camera is None or camera.desired_state != "running") and not stop_sent:
                commands.put_nowait(self._stop_command("desired_stopped"))
                stop_sent = True

    async def _persist_state(
        self,
        run: LiveCameraRun,
        worker_id: str,
        lease_token: str,
        event: StateEvent,
    ) -> None:
        async with self._session_factory() as session:
            updated = await self._runs.update_state(
                session,
                run.run_id,
                worker_id,
                lease_token,
                datetime.now(UTC),
                runtime_state=event.state,
            )
            await session.commit()
        if not updated:
            raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")
        if self._metrics is not None:
            for state in (
                "ACTIVE",
                "FAILED",
                "RECONNECTING",
                "STARTING",
                "STOPPED",
                "STOPPING",
            ):
                self._metrics.set("runtime_state", 1 if state == event.state else 0, state=state)

    async def _persist_metrics(
        self,
        run: LiveCameraRun,
        worker_id: str,
        lease_token: str,
        event: MetricsEvent,
    ) -> None:
        metrics = {"counters": event.counters, "gauges": event.gauges}
        if self._metrics is not None:
            for source, target in (
                ("decoded_frames", "frames_total"),
                ("tracked_objects", "tracked_objects_total"),
                ("eligible_objects", "eligible_objects_total"),
                ("embedding_count", "embeddings_total"),
                ("missing_embeddings", "missing_embeddings_total"),
                ("embedding_cosine_samples", "embedding_cosine_samples_total"),
            ):
                current = event.counters.get(source, 0)
                key = (run.run_id, source)
                previous = self._metric_counters.get(key, 0)
                if current >= previous:
                    self._metrics.increment(target, current - previous)
                self._metric_counters[key] = current
            dropped = event.counters.get("dropped_events", 0)
            dropped_key = (run.run_id, "dropped_events")
            previous_dropped = self._metric_counters.get(dropped_key, 0)
            if dropped >= previous_dropped:
                self._metrics.increment(
                    "protocol_dropped_total",
                    dropped - previous_dropped,
                    type="track_evidence",
                )
            self._metric_counters[dropped_key] = dropped
            self._metrics.set("frame_age_seconds", 0)
        async with self._session_factory() as session:
            updated = await self._runs.update_metrics(
                session,
                run.run_id,
                worker_id,
                lease_token,
                datetime.now(UTC),
                metrics,
            )
            await session.commit()
        if not updated:
            raise LiveLeaseLostError("LIVE_WORKER_LEASE_LOST")

    async def _finish(
        self,
        run: LiveCameraRun,
        worker_id: str,
        lease_token: str,
        runtime_state: str,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            await self._runs.finish(
                session,
                run.run_id,
                worker_id,
                lease_token,
                datetime.now(UTC),
                runtime_state=runtime_state,
                error_code=error_code,
                sanitized_error=redact_live_text(message) if message else None,
            )
            await session.commit()

    async def _finish_failed(
        self, run: LiveCameraRun, worker_id: str, lease_token: str, error_code: str
    ) -> None:
        await self._finish(run, worker_id, lease_token, "FAILED", error_code, error_code)

    def _start_command(self, run: LiveCameraRun, uri: str) -> StartCommand:
        header = ProtocolHeader(
            PROTOCOL_VERSION,
            "start",
            run.camera_id,
            run.camera_id,
            run.run_id,
            run.generation,
            1,
            1,
            run.traceparent,
            run.tracestate,
        )
        return StartCommand(
            header,
            uri,
            self._settings.live_worker_gpu_id,
            self._settings.live_pgie_config_path,
            self._settings.live_preprocess_config_path,
            self._settings.live_sgie_config_path,
            self._settings.live_tracker_config_path,
            f"/live/{run.camera_id}",
            self._settings.live_rtp_udp_port,
            self._settings.live_rtsp_output_port,
            self._settings.live_profile_version,
            "recognize",
            1,
            self._settings.min_confidence,
            self._settings.recognition_threshold,
            self._settings.video_track_vote_min_margin,
            int(self._settings.video_appearance_max_gap_seconds * 1_000_000_000),
            self._settings.live_latency_ms,
            self._settings.live_reconnect_interval_seconds,
            self._settings.live_reconnect_attempts,
            self._settings.live_frame_timeout_ns,
            False,
            True,
        )

    def _stop_command(self, reason: str) -> StopCommand:
        sequence = self._command_sequence
        self._command_sequence += 1
        if self._active_header is None:
            camera_id = "00000000-0000-0000-0000-000000000000"
            session_id = camera_id
            run_id = camera_id
            generation = 1
            runtime_attempt = 1
            traceparent = f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
            tracestate = None
        else:
            active = self._active_header
            session_id = active.session_id
            camera_id = active.camera_id
            run_id = active.run_id
            generation = active.generation
            runtime_attempt = active.runtime_attempt
            traceparent = active.traceparent
            tracestate = active.tracestate
        return StopCommand(
            ProtocolHeader(
                PROTOCOL_VERSION,
                "stop",
                session_id,
                camera_id,
                run_id,
                generation,
                runtime_attempt,
                sequence,
                traceparent,
                tracestate,
            ),
            reason,
            time.monotonic_ns() + 5_000_000_000,
        )
