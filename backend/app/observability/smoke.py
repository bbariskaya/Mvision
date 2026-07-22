import logging

from opentelemetry.trace import Status, StatusCode

from app.config import get_settings
from app.observability.telemetry import TelemetryRuntime, configure_telemetry

ERROR_CODE = "OBSERVABILITY_SMOKE_TEST"
LOGGER_NAME = "app.observability.smoke"
logger = logging.getLogger(LOGGER_NAME)


def emit_error_smoke(runtime: TelemetryRuntime) -> str:
    with runtime.start_span(
        "live.camera.run",
        {"operation": "live.camera.run", "error_code": ERROR_CODE},
    ) as span:
        span.set_status(Status(StatusCode.ERROR, ERROR_CODE))
        logger.error("Observability smoke test", extra={"error_code": ERROR_CODE})
        return f"{span.get_span_context().trace_id:032x}"


def main() -> int:
    settings = get_settings().model_copy(
        update={
            "otel_enabled": True,
            "otel_service_name": "mvision-live-worker",
            "otel_service_instance_id": "observability-smoke",
        }
    )
    runtime = configure_telemetry(settings)
    try:
        if not runtime.enabled:
            return 2
        trace_id = emit_error_smoke(runtime)
        timeout_millis = int(settings.otel_shutdown_timeout_seconds * 1_000)
        if not runtime.force_flush(timeout_millis):
            return 3
        print(trace_id)
        return 0
    finally:
        runtime.shutdown(int(settings.otel_shutdown_timeout_seconds * 1_000))


if __name__ == "__main__":
    raise SystemExit(main())
