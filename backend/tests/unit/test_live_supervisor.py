import asyncio
import time
from collections import deque
from types import SimpleNamespace

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry
from pydantic import SecretStr

from app.config import Settings
from app.infrastructure.live.protocol import (
    IdentityAssignment,
    MetricsEvent,
    NativeOperationEvent,
    ProtocolHeader,
    StateEvent,
    StopCommand,
    StoppedEvent,
)
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.observability.metrics import create_metrics
from app.observability.telemetry import configure_telemetry
from app.services.face_matcher import FaceMatch
from app.services.live_event_service import LiveEventService
from app.services.live_identity_service import LiveIdentityService
from app.services.live_supervisor import LiveSupervisor
from app.services.video_identity_voting_service import VideoIdentityDecision
from app.worker.live_worker_main import run_worker
from tests.unit.test_live_identity_service import _event

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _header(message_type: str, sequence: int, generation: int = 1) -> ProtocolHeader:
    return ProtocolHeader(
        1,
        message_type,
        CAMERA_ID,
        RUN_ID,
        generation,
        sequence,
        TRACEPARENT,
        None,
    )


def _run(generation: int = 1, traceparent: str = TRACEPARENT):
    return SimpleNamespace(
        run_id=RUN_ID,
        camera_id=CAMERA_ID,
        generation=generation,
        runtime_state="STARTING",
        traceparent=traceparent,
        tracestate=None,
    )


def _camera(desired_state: str = "running"):
    return SimpleNamespace(
        camera_id=CAMERA_ID,
        uri_ciphertext="encrypted-uri",
        desired_state=desired_state,
    )


class _Session:
    def __init__(self, commits: list[int]):
        self._commits = commits

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def commit(self) -> None:
        self._commits.append(1)


class _Sessions:
    def __init__(self):
        self.commits: list[int] = []

    def __call__(self):
        return _Session(self.commits)


class _Runs:
    def __init__(self, claims):
        self.claims = deque(claims)
        self.renew_result = True
        self.state_result = True
        self.renew_count = 0
        self.states: list[dict] = []
        self.metrics: list[dict] = []
        self.finishes: list[dict] = []

    async def claim(self, session, **kwargs):
        return self.claims.popleft() if self.claims else None

    async def renew(self, session, *args, **kwargs):
        self.renew_count += 1
        return self.renew_result

    async def update_state(self, session, *args, **kwargs):
        self.states.append(kwargs)
        return self.state_result

    async def update_metrics(self, session, *args, **kwargs):
        self.metrics.append(args[-1] if args else kwargs["metrics"])
        return True

    async def finish(self, session, *args, **kwargs):
        self.finishes.append(kwargs)
        return True


class _Cameras:
    def __init__(self, states=("running",)):
        self.states = deque(states)
        self.last = "running"

    async def get(self, session, camera_id):
        if self.states:
            self.last = self.states.popleft()
        return _camera(self.last)


class _Cipher:
    def decrypt(self, ciphertext: str) -> SecretStr:
        assert ciphertext == "encrypted-uri"
        return SecretStr("rtsp://admin:secret@camera.invalid/live")


class _CompletedRunner:
    def __init__(self):
        self.starts = []

    async def run(self, start, on_event, commands):
        self.starts.append(start)
        events = (
            StateEvent(_header("state", 10), "ACTIVE", "first_frame"),
            MetricsEvent(_header("metrics", 11), {"decoded_frames": 4}, {"fps": 25.0}),
            StoppedEvent(_header("stopped", 12), 4, 1, 0, True, "operator"),
        )
        for event in events:
            result = on_event(event)
            if asyncio.iscoroutine(result):
                await result
        return events[-1]


class _RecognitionMetricsRunner:
    async def run(self, start, on_event, commands):
        for sequence, counters in (
            (
                10,
                {
                    "decoded_frames": 100,
                    "tracked_objects": 30,
                    "eligible_objects": 20,
                    "embedding_count": 18,
                    "missing_embeddings": 2,
                    "embedding_cosine_samples": 12,
                    "dropped_events": 0,
                },
            ),
            (
                11,
                {
                    "decoded_frames": 140,
                    "tracked_objects": 44,
                    "eligible_objects": 29,
                    "embedding_count": 26,
                    "missing_embeddings": 3,
                    "embedding_cosine_samples": 18,
                    "dropped_events": 0,
                },
            ),
        ):
            result = on_event(MetricsEvent(_header("metrics", sequence), counters, {}))
            if asyncio.iscoroutine(result):
                await result
        stopped = StoppedEvent(_header("stopped", 12), 140, 44, 0, True, "operator")
        result = on_event(stopped)
        if asyncio.iscoroutine(result):
            await result
        return stopped


class _WaitingRunner:
    def __init__(self):
        self.command = None
        self.cancelled = False

    async def run(self, start, on_event, commands):
        try:
            self.command = await commands.get()
            stopped = StoppedEvent(
                _header("stopped", 12), 0, 0, 0, True, "desired_stopped"
            )
            result = on_event(stopped)
            if asyncio.iscoroutine(result):
                await result
            return stopped
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _CrashingRunner:
    async def run(self, start, on_event, commands):
        raise RuntimeError("native crashed rtsp://admin:secret@camera.invalid/live")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        live_worker_lease_seconds=1,
        live_worker_gpu_id=0,
    )


def _supervisor(
    runs,
    cameras,
    runner,
    sessions,
    *,
    interval=0.01,
    telemetry=None,
    identity_service=None,
    event_service=None,
    metrics=None,
) -> LiveSupervisor:
    return LiveSupervisor(
        _settings(),
        cameras,
        runs,
        _Cipher(),
        runner,
        identity_service=identity_service,
        event_service=event_service,
        telemetry=telemetry,
        metrics=metrics,
        session_factory=sessions,
        monitor_interval_seconds=interval,
    )


class _NativeOperationRunner:
    async def run(self, start, on_event, commands):
        started = time.monotonic_ns()
        events = (
            NativeOperationEvent(
                _header("native_operation", 10),
                "source_connect",
                started,
                started + 25_000_000,
                "ok",
                None,
                {},
            ),
            StoppedEvent(_header("stopped", 11), 1, 0, 0, True, "operator"),
        )
        for event in events:
            result = on_event(event)
            if asyncio.iscoroutine(result):
                await result
        return events[-1]


@pytest.mark.asyncio
async def test_worker_trace_tree_preserves_parent_and_native_duration() -> None:
    span_exporter = InMemorySpanExporter()
    telemetry = configure_telemetry(
        Settings(_env_file=None, otel_enabled=True, otel_bsp_schedule_delay_millis=10),
        span_exporter=span_exporter,
        log_exporter=InMemoryLogRecordExporter(),
    )
    metrics = create_metrics(CollectorRegistry())

    assert await _supervisor(
        _Runs([_run()]),
        _Cameras(),
        _NativeOperationRunner(),
        _Sessions(),
        telemetry=telemetry,
        metrics=metrics,
    ).process_one_camera("worker-1")
    assert telemetry.force_flush(1_000)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert set(spans) == {
        "live.supervisor.claim",
        "live.camera.run",
        "live.native.source_connect",
    }
    assert spans["live.supervisor.claim"].parent is not None
    assert spans["live.supervisor.claim"].parent.span_id == int("00f067aa0ba902b7", 16)
    assert spans["live.camera.run"].parent is not None
    assert spans["live.camera.run"].parent.span_id == spans[
        "live.supervisor.claim"
    ].context.span_id
    assert spans["live.native.source_connect"].parent is not None
    assert spans["live.native.source_connect"].parent.span_id == spans[
        "live.camera.run"
    ].context.span_id
    assert (
        spans["live.native.source_connect"].end_time
        - spans["live.native.source_connect"].start_time
        == 25_000_000
    )
    assert 'operation="source_connect",status="success"' in metrics.render_metrics()[
        0
    ].decode()
    telemetry.shutdown(1_000)


class _BatchClient:
    async def query_batch_points(self, **kwargs):
        return [SimpleNamespace(points=[]) for _ in kwargs["requests"]]


class _TracingVoter:
    def __init__(self, qdrant, match):
        self._qdrant = qdrant
        self._match = match

    async def resolve(self, track):
        await self._qdrant.search_batch([[1.0] + [0.0] * 511])
        return VideoIdentityDecision(self._match, self._match.score)


class _ReferenceVectors:
    async def get(self, sample_id):
        return {"vector": [1.0] + [0.0] * 511}


class _EventRepository:
    async def create_once(self, session, event):
        return event


class _SnapshotStorage:
    async def upload_live_snapshot(self, object_key, data, event_id):
        return SimpleNamespace(bucket="live", object_key=object_key)

    async def delete_live_snapshot(self, object_key):
        pass


class _Notifier:
    async def publish(self, event):
        pass


class _IdentityRunner:
    async def run(self, start, on_event, commands):
        started = time.monotonic_ns()
        events = (
            NativeOperationEvent(
                _header("native_operation", 10),
                "source_connect",
                started,
                started + 1_000_000,
                "ok",
                None,
                {},
            ),
            NativeOperationEvent(
                _header("native_operation", 11),
                "first_frame",
                started + 2_000_000,
                started + 3_000_000,
                "ok",
                None,
                {},
            ),
            _event((1.0, 0.0)),
            StoppedEvent(_header("stopped", 13), 1, 1, 0, True, "operator"),
        )
        for event in events:
            result = on_event(event)
            if asyncio.iscoroutine(result):
                await result
        return events[-1]


@pytest.mark.asyncio
async def test_complete_semantic_trace_tree_has_exact_operation_boundaries() -> None:
    span_exporter = InMemorySpanExporter()
    telemetry = configure_telemetry(
        Settings(_env_file=None, otel_enabled=True, otel_bsp_schedule_delay_millis=10),
        span_exporter=span_exporter,
        log_exporter=InMemoryLogRecordExporter(),
    )
    settings = _settings()
    qdrant = QdrantAdapter(settings, telemetry)
    qdrant._setup_complete = True
    qdrant._client = _BatchClient()
    identity = SimpleNamespace(
        face_id="019b0000-0000-7000-8000-000000000003",
        name="Ada Secretperson",
        lifecycle_status="known",
        version=1,
    )
    match = FaceMatch(identity, "sample-1", 0.91)
    identity_service = LiveIdentityService(
        settings,
        _TracingVoter(qdrant, match),
        _ReferenceVectors(),
        telemetry,
    )
    event_service = LiveEventService(
        settings,
        _EventRepository(),
        _SnapshotStorage(),
        _Notifier(),
        telemetry=telemetry,
        session_factory=_Sessions(),
    )
    with telemetry.start_span("http.camera.start"):
        persisted_traceparent, _ = telemetry.trace_headers()

    assert await _supervisor(
        _Runs([_run(traceparent=persisted_traceparent)]),
        _Cameras(),
        _IdentityRunner(),
        _Sessions(),
        telemetry=telemetry,
        identity_service=identity_service,
        event_service=event_service,
    ).process_one_camera("worker-1")
    assert telemetry.force_flush(1_000)

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    assert set(spans) == {
        "http.camera.start",
        "live.supervisor.claim",
        "live.camera.run",
        "live.native.source_connect",
        "live.native.first_frame",
        "live.identity.resolve",
        "live.qdrant.search",
        "live.snapshot.upload",
        "live.event.commit",
        "live.notification.publish",
    }
    assert spans["live.supervisor.claim"].parent is not None
    assert spans["live.supervisor.claim"].parent.span_id == spans[
        "http.camera.start"
    ].context.span_id
    run_span_id = spans["live.camera.run"].context.span_id
    for name in (
        "live.native.source_connect",
        "live.native.first_frame",
        "live.identity.resolve",
        "live.snapshot.upload",
        "live.event.commit",
        "live.notification.publish",
    ):
        assert spans[name].parent is not None
        assert spans[name].parent.span_id == run_span_id
    assert spans["live.qdrant.search"].parent is not None
    assert spans["live.qdrant.search"].parent.span_id == spans[
        "live.identity.resolve"
    ].context.span_id
    telemetry.shutdown(1_000)


@pytest.mark.asyncio
async def test_returns_false_without_a_camera_claim() -> None:
    sessions = _Sessions()
    supervisor = _supervisor(_Runs([None]), _Cameras(), _CompletedRunner(), sessions)

    assert not await supervisor.process_one_camera("worker-1")
    assert sessions.commits


@pytest.mark.asyncio
async def test_claims_runs_native_and_persists_fenced_events() -> None:
    sessions = _Sessions()
    runs = _Runs([_run()])
    runner = _CompletedRunner()

    assert await _supervisor(runs, _Cameras(), runner, sessions).process_one_camera(
        "worker-1"
    )

    assert runner.starts[0].uri == "rtsp://admin:secret@camera.invalid/live"
    assert runner.starts[0].header.generation == 1
    assert runs.states[-1]["runtime_state"] == "ACTIVE"
    assert runs.metrics == [{"counters": {"decoded_frames": 4}, "gauges": {"fps": 25.0}}]
    assert runs.finishes[-1]["runtime_state"] == "STOPPED"
    assert len(sessions.commits) >= 4


@pytest.mark.asyncio
async def test_native_recognition_counters_are_exported_as_exact_prometheus_deltas() -> None:
    metrics = create_metrics(CollectorRegistry())

    assert await _supervisor(
        _Runs([_run()]),
        _Cameras(),
        _RecognitionMetricsRunner(),
        _Sessions(),
        metrics=metrics,
    ).process_one_camera("worker-1")

    rendered = metrics.render_metrics()[0].decode()
    assert "mvision_live_frames_total 140.0" in rendered
    assert "mvision_live_tracked_objects_total 44.0" in rendered
    assert "mvision_live_eligible_objects_total 29.0" in rendered
    assert "mvision_live_embeddings_total 26.0" in rendered
    assert "mvision_live_missing_embeddings_total 3.0" in rendered
    assert "mvision_live_embedding_cosine_samples_total 18.0" in rendered


@pytest.mark.asyncio
async def test_desired_stop_enqueues_stop_command() -> None:
    sessions = _Sessions()
    runs = _Runs([_run()])
    runner = _WaitingRunner()
    cameras = _Cameras(("running", "stopped"))

    assert await _supervisor(runs, cameras, runner, sessions).process_one_camera(
        "worker-1"
    )

    assert isinstance(runner.command, StopCommand)
    assert runner.command.reason == "desired_stopped"


@pytest.mark.asyncio
async def test_lost_lease_cancels_child_and_abandons_terminal_mutation() -> None:
    sessions = _Sessions()
    runs = _Runs([_run()])
    runs.renew_result = False
    runner = _WaitingRunner()

    assert await _supervisor(runs, _Cameras(), runner, sessions).process_one_camera(
        "worker-1"
    )

    assert runner.cancelled
    assert runs.finishes == []


@pytest.mark.asyncio
async def test_fenced_event_rejection_cancels_lease_monitor() -> None:
    sessions = _Sessions()
    runs = _Runs([_run()])
    runs.state_result = False

    assert await _supervisor(
        runs, _Cameras(), _CompletedRunner(), sessions
    ).process_one_camera("worker-1")
    renewals_at_return = runs.renew_count
    await asyncio.sleep(0.03)

    assert runs.finishes == []
    assert runs.renew_count == renewals_at_return


@pytest.mark.asyncio
async def test_crash_is_sanitized_and_next_claim_uses_new_generation() -> None:
    sessions = _Sessions()
    runs = _Runs([_run(1), _run(2)])
    supervisor = _supervisor(runs, _Cameras(), _CrashingRunner(), sessions)

    assert await supervisor.process_one_camera("worker-1")
    assert await supervisor.process_one_camera("worker-1")

    assert [item["runtime_state"] for item in runs.finishes] == ["FAILED", "FAILED"]
    assert all("secret" not in item["sanitized_error"] for item in runs.finishes)


@pytest.mark.asyncio
async def test_worker_sleeps_only_after_no_claim_and_honors_shutdown() -> None:
    shutdown = asyncio.Event()

    class _Supervisor:
        def __init__(self):
            self.calls = 0

        async def process_one_camera(self, worker_id: str) -> bool:
            assert worker_id == "worker-1"
            self.calls += 1
            if self.calls == 2:
                shutdown.set()
            return self.calls == 1

    supervisor = _Supervisor()
    await run_worker(supervisor, "worker-1", 0.0, shutdown)

    assert supervisor.calls == 2


@pytest.mark.asyncio
async def test_track_evidence_is_resolved_off_callback_and_enqueues_assignment() -> None:
    evidence = _event((1.0, 0.0))
    assignment = IdentityAssignment(
        ProtocolHeader(
            1, "identity_assignment", CAMERA_ID, RUN_ID, 1, 20, TRACEPARENT, None
        ),
        42,
        1,
        1,
        "unknown",
        None,
        None,
        None,
        None,
        None,
        1,
    )

    class _Identity:
        async def resolve(self, received):
            assert received is evidence
            return "decision"

    class _EventService:
        async def accept_decision(self, camera_id, run_id, generation, received, decision):
            assert (camera_id, run_id, generation) == (CAMERA_ID, RUN_ID, 1)
            assert received is evidence
            assert decision == "decision"
            return (assignment,)

    class _EvidenceRunner(_CompletedRunner):
        async def run(self, start, on_event, commands):
            result = on_event(evidence)
            if asyncio.iscoroutine(result):
                await result
            stopped = StoppedEvent(
                _header("stopped", 21), 1, 1, 0, True, "operator"
            )
            result = on_event(stopped)
            if asyncio.iscoroutine(result):
                await result
            self.commands = commands
            return stopped

    sessions = _Sessions()
    runs = _Runs([_run()])
    runner = _EvidenceRunner()
    supervisor = LiveSupervisor(
        _settings(),
        _Cameras(),
        runs,
        _Cipher(),
        runner,
        identity_service=_Identity(),
        event_service=_EventService(),
        session_factory=sessions,
        monitor_interval_seconds=0.01,
    )

    assert await supervisor.process_one_camera("worker-1")
    assert runner.commands.get_nowait() == assignment
