import asyncio
import logging
import secrets
import time
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import LiveCameraRun
from app.infrastructure.database.repositories import LiveCameraRepository, LiveRunRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.live.native_runner import (
    LiveCommandQueue,
    NativeLiveRunner,
    NativeLiveRunnerError,
)
from app.infrastructure.live.protocol import (
    FailedEvent,
    LiveMessage,
    MetricsEvent,
    ProtocolHeader,
    StartCommand,
    StateEvent,
    StopCommand,
    TrackEvidenceEvent,
    TrackExpiredEvent,
)
from app.infrastructure.live.uri_cipher import LiveUriCipher, redact_live_text

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
        self._session_factory = session_factory
        self._monitor_interval = monitor_interval_seconds or max(
            1.0, settings.live_worker_lease_seconds / 3
        )
        self._active_commands: LiveCommandQueue | None = None
        self._active_header: ProtocolHeader | None = None
        self._command_sequence = 2

    async def process_one_camera(self, worker_id: str) -> bool:
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
            camera = (
                await self._cameras.get(session, run.camera_id) if run is not None else None
            )
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
                elif isinstance(event, (TrackEvidenceEvent, TrackExpiredEvent)):
                    if identity_queue is not None:
                        try:
                            identity_queue.put_nowait(event)
                        except asyncio.QueueFull:
                            logger.warning("Live identity work queue full; event dropped")

            runner_task = asyncio.create_task(self._runner.run(start, on_event, commands))
            monitor_task = asyncio.create_task(
                self._monitor(run, worker_id, lease_token, commands)
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
            if not lease_lost:
                error_code = (
                    exc.error_code
                    if isinstance(exc, NativeLiveRunnerError)
                    else "LIVE_PIPELINE_ERROR"
                )
                await self._finish(
                    run, worker_id, lease_token, "FAILED", error_code, str(exc)
                )
            return True
        finally:
            for task in (runner_task, monitor_task, identity_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(
                    task
                    for task in (runner_task, monitor_task, identity_task)
                    if task is not None
                ),
                return_exceptions=True,
            )
            self._active_commands = None
            self._active_header = None
            plaintext_uri = None
            start = None

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
                logger.exception("Live identity event processing failed")
            finally:
                queue.task_done()

    def request_stop(self, reason: str = "worker_shutdown") -> None:
        if self._active_commands is None:
            return
        self._active_commands.put_nowait(self._stop_command(reason))

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

    async def _persist_metrics(
        self,
        run: LiveCameraRun,
        worker_id: str,
        lease_token: str,
        event: MetricsEvent,
    ) -> None:
        metrics = {"counters": event.counters, "gauges": event.gauges}
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
            1,
            "start",
            run.camera_id,
            run.run_id,
            run.generation,
            1,
            f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01",
            None,
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
            self._settings.live_latency_ms,
            self._settings.live_reconnect_interval_seconds,
            self._settings.live_reconnect_attempts,
            self._settings.live_frame_timeout_ns,
        )

    def _stop_command(self, reason: str) -> StopCommand:
        sequence = self._command_sequence
        self._command_sequence += 1
        if self._active_header is None:
            camera_id = "00000000-0000-0000-0000-000000000000"
            run_id = camera_id
            generation = 1
            traceparent = f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
        else:
            active = self._active_header
            camera_id = active.camera_id
            run_id = active.run_id
            generation = active.generation
            traceparent = active.traceparent
        return StopCommand(
            ProtocolHeader(
                1,
                "stop",
                camera_id,
                run_id,
                generation,
                sequence,
                traceparent,
                None,
            ),
            reason,
            time.monotonic_ns() + 5_000_000_000,
        )
