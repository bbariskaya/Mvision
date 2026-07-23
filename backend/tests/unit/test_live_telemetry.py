import logging
from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from app.config import Settings
from app.observability.telemetry import configure_telemetry


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "otel_enabled": True,
        "otel_service_name": "mvision-test",
        "otel_service_version": "9.8.7",
        "otel_deployment_environment": "test",
        "otel_service_instance_id": "test-0",
        "otel_bsp_schedule_delay_millis": 10,
    }
    values.update(overrides)
    return Settings(**values)


def test_runtime_exports_resource_parent_timestamps_and_correlated_logs() -> None:
    span_exporter = InMemorySpanExporter()
    log_exporter = InMemoryLogRecordExporter()
    runtime = configure_telemetry(
        _settings(), span_exporter=span_exporter, log_exporter=log_exporter
    )
    parent_context = trace.set_span_in_context(
        trace.NonRecordingSpan(
            trace.SpanContext(
                trace_id=int("1" * 32, 16),
                span_id=int("2" * 16, 16),
                is_remote=True,
                trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
            )
        )
    )
    start_time = 1_700_000_000_000_000_000

    with runtime.start_span(
        "live.camera.run",
        {
            "camera_id": "019b0000-0000-7000-8000-000000000001",
            "source_uri": "rtsp://secret",
        },
        context=parent_context,
        start_time=start_time,
    ) as span:
        logging.getLogger("app.telemetry.test").warning("camera state changed")
        traceparent, tracestate = runtime.trace_headers()

    assert runtime.force_flush(1_000) is True
    finished = span_exporter.get_finished_spans()
    assert len(finished) == 1
    exported_span = finished[0]
    assert exported_span.start_time == start_time
    assert exported_span.parent is not None
    assert exported_span.parent.span_id == int("2" * 16, 16)
    assert exported_span.attributes == {"camera_id": "019b0000-0000-7000-8000-000000000001"}
    assert exported_span.resource.attributes["service.name"] == "mvision-test"
    assert exported_span.resource.attributes["service.version"] == "9.8.7"
    assert exported_span.resource.attributes["deployment.environment"] == "test"
    assert exported_span.resource.attributes["service.instance.id"] == "test-0"
    assert traceparent.startswith(f"00-{span.get_span_context().trace_id:032x}-")
    assert tracestate is None

    records = log_exporter.get_finished_logs()
    assert len(records) == 1
    assert records[0].log_record.trace_id == span.get_span_context().trace_id
    assert records[0].log_record.span_id == span.get_span_context().span_id
    runtime.shutdown(1_000)


def test_disabled_runtime_is_noop_even_with_exporters() -> None:
    span_exporter = InMemorySpanExporter()
    log_exporter = InMemoryLogRecordExporter()
    runtime = configure_telemetry(
        _settings(otel_enabled=False),
        span_exporter=span_exporter,
        log_exporter=log_exporter,
    )

    with runtime.start_span("live.camera.run", {"camera_id": "camera-1"}) as span:
        assert span.is_recording() is False
        assert runtime.trace_headers() == ("", None)

    assert runtime.force_flush(10) is True
    runtime.shutdown(10)
    runtime.shutdown(10)
    assert span_exporter.get_finished_spans() == ()
    assert log_exporter.get_finished_logs() == ()


def test_http_middleware_extracts_strict_w3c_context_for_allowlisted_routes() -> None:
    span_exporter = InMemorySpanExporter()
    runtime = configure_telemetry(
        _settings(),
        span_exporter=span_exporter,
        log_exporter=InMemoryLogRecordExporter(),
    )
    app = FastAPI()
    runtime.install_http_middleware(app)
    runtime.install_http_middleware(app)

    @app.post("/api/v1/cameras/{camera_id}/start")
    async def start_camera(camera_id: str) -> dict[str, str]:
        traceparent, _ = runtime.trace_headers()
        return {"traceparent": traceparent, "cameraId": camera_id}

    @app.get("/api/v1/cameras/{camera_id}/health")
    async def camera_health(camera_id: str) -> dict[str, str]:
        return {"cameraId": camera_id}

    incoming_trace_id = "3" * 32
    incoming_span_id = "4" * 16
    response = TestClient(app).post(
        "/api/v1/cameras/camera-1/start",
        headers={"traceparent": f"00-{incoming_trace_id}-{incoming_span_id}-01"},
    )
    assert TestClient(app).get("/api/v1/cameras/camera-1/health").status_code == 200

    assert response.status_code == 200
    assert response.json()["traceparent"].startswith(f"00-{incoming_trace_id}-")
    assert runtime.force_flush(1_000) is True
    finished = span_exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "http.camera.start"
    assert finished[0].parent is not None
    assert finished[0].parent.span_id == int(incoming_span_id, 16)
    assert finished[0].attributes == {
        "operation": "http.camera.start",
        "status": 200,
    }
    runtime.shutdown(1_000)


class _BrokenSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        raise RuntimeError("collector unavailable: rtsp://must-not-leak")

    def shutdown(self) -> None:
        pass


def test_exporter_failure_does_not_escape_product_code_or_shutdown() -> None:
    runtime = configure_telemetry(_settings(), span_exporter=_BrokenSpanExporter())

    with runtime.start_span("live.camera.run"):
        product_result = "unchanged"

    assert product_result == "unchanged"
    assert isinstance(runtime.force_flush(1_000), bool)
    runtime.shutdown(1_000)
    runtime.shutdown(1_000)


@pytest.mark.asyncio
async def test_api_lifespan_initializes_dependencies_then_shuts_down_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    events: list[str] = []

    class _Dependency:
        def __init__(self, name: str) -> None:
            self._name = name

        async def ensure_bucket(self) -> None:
            events.append(self._name)

        async def setup(self) -> None:
            events.append(self._name)

    class _Runtime:
        def shutdown(self, timeout_millis: int) -> None:
            assert timeout_millis == 3_000
            events.append("telemetry.shutdown")

    class _MediaClient:
        async def aclose(self) -> None:
            events.append("mediamtx.close")

    container = SimpleNamespace(
        minio=_Dependency("minio"),
        qdrant=_Dependency("qdrant"),
        mediamtx_client=_MediaClient(),
    )
    monkeypatch.setattr(main_module, "get_container", lambda *args: container)
    test_app = FastAPI()
    test_app.state.telemetry = _Runtime()

    async with main_module.lifespan(test_app):
        events.append("serving")

    assert events == [
        "minio",
        "qdrant",
        "serving",
        "mediamtx.close",
        "telemetry.shutdown",
    ]


@pytest.mark.asyncio
async def test_live_worker_telemetry_shutdown_cannot_change_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import live_worker_main

    settings = _settings(otel_enabled=False)
    configured: list[Settings] = []
    metrics_bind: list[tuple[int, str]] = []

    class _Runtime:
        def shutdown(self, timeout_millis: int) -> None:
            raise RuntimeError("collector unavailable: rtsp://must-not-leak")

    class _Loop:
        def add_signal_handler(self, selected_signal: object, callback: object) -> None:
            pass

    class _MetricsServer:
        def shutdown(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    class _MetricsThread:
        def join(self, timeout: float) -> None:
            assert timeout == settings.otel_shutdown_timeout_seconds

    async def run_worker_once(*args: object) -> None:
        return None

    def configure(selected: Settings) -> _Runtime:
        configured.append(selected)
        return _Runtime()

    def start_metrics_server(port: int, *, addr: str, registry: object) -> tuple:
        metrics_bind.append((port, addr))
        return _MetricsServer(), _MetricsThread()

    container = SimpleNamespace(
        live_supervisor=SimpleNamespace(), settings=SimpleNamespace(live_worker_poll_seconds=1)
    )
    monkeypatch.setattr(live_worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(live_worker_main, "configure_telemetry", configure)
    monkeypatch.setattr(live_worker_main, "get_container", lambda *args: container)
    monkeypatch.setattr(live_worker_main, "run_worker", run_worker_once)
    monkeypatch.setattr(live_worker_main, "start_http_server", start_metrics_server)
    monkeypatch.setattr(live_worker_main.asyncio, "get_running_loop", lambda: _Loop())
    monkeypatch.setenv("LIVE_WORKER_ID", "worker-test-0")

    await live_worker_main.main()

    assert configured[0].otel_service_name == "mvision-live-worker"
    assert configured[0].otel_service_instance_id == "worker-test-0"
    assert metrics_bind == [(9464, "0.0.0.0")]


@pytest.mark.parametrize(
    ("overrides", "error_fragment"),
    [
        ({"otel_export_timeout_seconds": 0}, "otel_export_timeout_seconds"),
        ({"otel_shutdown_timeout_seconds": 0}, "otel_shutdown_timeout_seconds"),
        ({"otel_bsp_max_queue_size": 0}, "otel_bsp_max_queue_size"),
        ({"otel_bsp_max_export_batch_size": 0}, "otel_bsp_max_export_batch_size"),
        ({"otel_bsp_schedule_delay_millis": 0}, "otel_bsp_schedule_delay_millis"),
        (
            {"otel_bsp_max_queue_size": 8, "otel_bsp_max_export_batch_size": 9},
            "OTEL_BATCH_SIZE_EXCEEDS_QUEUE_SIZE",
        ),
    ],
)
def test_telemetry_settings_reject_invalid_bounds(
    overrides: dict[str, object], error_fragment: str
) -> None:
    with pytest.raises(ValidationError, match=error_fragment):
        _settings(**overrides)
