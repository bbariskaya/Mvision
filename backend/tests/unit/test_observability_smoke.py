from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.config import Settings
from app.observability import smoke
from app.observability.smoke import emit_error_smoke
from app.observability.telemetry import configure_telemetry


def test_smoke_uses_an_explicit_application_logger_when_run_as_a_module() -> None:
    assert smoke.LOGGER_NAME == "app.observability.smoke"
    assert smoke.logger.name == smoke.LOGGER_NAME


def test_smoke_emits_one_safe_error_span_and_correlated_log() -> None:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    runtime = configure_telemetry(
        Settings(_env_file=None, otel_enabled=True, otel_bsp_schedule_delay_millis=10),
        span_exporter=spans,
        log_exporter=logs,
    )
    try:
        trace_id = emit_error_smoke(runtime)
        assert runtime.force_flush(1_000)

        span = spans.get_finished_spans()[0]
        record = logs.get_finished_logs()[0].log_record
        assert trace_id == f"{span.context.trace_id:032x}"
        assert record.trace_id == span.context.trace_id
        assert span.status.status_code is StatusCode.ERROR
        assert span.attributes["error_code"] == "OBSERVABILITY_SMOKE_TEST"
        assert record.attributes["error_code"] == "OBSERVABILITY_SMOKE_TEST"
        assert record.body == "Observability smoke test"
    finally:
        runtime.shutdown(1_000)
