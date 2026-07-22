import logging
import re
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext

from opentelemetry import trace
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.context import Context, get_current
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, ReadableLogRecord
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    LogRecordExportResult,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.infrastructure.live.protocol import validate_trace_context
from app.infrastructure.live.uri_cipher import redact_live_text
from app.observability.semantic import (
    ALLOWED_ATTRIBUTE_KEYS,
    SPAN_NAMES,
    native_span_name,
    sanitize_attributes,
)

_LOCAL_LOGGER = logging.getLogger("mvision.telemetry.local")
_LOCAL_LOGGER.propagate = False
if not _LOCAL_LOGGER.handlers:
    _LOCAL_LOGGER.addHandler(logging.StreamHandler())


def _local_warning(message: str) -> None:
    _LOCAL_LOGGER.warning(message)


class _SafeLoggingHandler(logging.Handler):
    _CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
    _SAFE_MESSAGES = frozenset(
        {
            "Live identity event processing failed",
            "Live identity query failed",
            "Live identity reference retrieval failed",
            "Live identity work queue full; event dropped",
            "Metrics endpoint shutdown failed; worker exit continues",
            "Metrics endpoint startup failed; worker processing continues",
            "Native live worker diagnostic",
            "Native operation timestamp outside run boundary; event dropped",
            "Observability smoke test",
            "Telemetry shutdown failed; worker exit continues",
        }
    )

    def __init__(self, logger_provider: LoggerProvider) -> None:
        super().__init__()
        self._logger_provider = logger_provider

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("app."):
            return
        template = redact_live_text(str(record.msg))
        body = (
            template
            if template in self._SAFE_MESSAGES or record.args
            else "Application diagnostic"
        )
        body = self._CONTROL_CHARACTERS.sub(" ", body)[:256]
        attributes = sanitize_attributes(
            {
                key: getattr(record, key, None)
                for key in ALLOWED_ATTRIBUTE_KEYS
            }
        )
        severity = SeverityNumber.INFO
        if record.levelno >= logging.ERROR:
            severity = SeverityNumber.ERROR
        elif record.levelno >= logging.WARNING:
            severity = SeverityNumber.WARN
        elif record.levelno < logging.INFO:
            severity = SeverityNumber.DEBUG
        self._logger_provider.get_logger(record.name).emit(
            LogRecord(
                timestamp=int(record.created * 1_000_000_000),
                observed_timestamp=time.time_ns(),
                context=get_current(),
                severity_text=record.levelname,
                severity_number=severity,
                body=body,
                attributes=attributes,
            )
        )


def _http_operation(scope: Scope) -> str | None:
    if scope["type"] != "http" or scope["method"] != "POST":
        return None
    parts = scope["path"].strip("/").split("/")
    if parts == ["api", "v1", "cameras"]:
        return "http.camera.register"
    if len(parts) == 5 and parts[:3] == ["api", "v1", "cameras"]:
        return {
            "start": "http.camera.start",
            "stop": "http.camera.stop",
        }.get(parts[4])
    return None


class _TelemetryMiddleware:
    def __init__(self, app: ASGIApp, runtime: "TelemetryRuntime") -> None:
        self._app = app
        self._runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        operation = _http_operation(scope)
        if operation is None or not self._runtime.enabled:
            await self._app(scope, receive, send)
            return
        headers = {
            key.decode("ascii").lower(): value.decode("ascii")
            for key, value in scope["headers"]
            if key.lower() in {b"traceparent", b"tracestate"}
        }
        parent_context = self._runtime._propagator.extract(headers)
        with self._runtime.start_span(
            operation, {"operation": operation}, context=parent_context
        ) as span:

            async def send_with_status(message: Message) -> None:
                if message["type"] == "http.response.start":
                    span.set_attribute("status", message["status"])
                await send(message)

            try:
                await self._app(scope, receive, send_with_status)
            except Exception:
                span.set_attribute("error_code", "UNHANDLED_EXCEPTION")
                raise


class _FailOpenSpanExporter(SpanExporter):
    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            return self._exporter.export(spans)
        except Exception:
            _local_warning("Telemetry span export failed; application processing continues")
            return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return self._exporter.force_flush(timeout_millis)
        except Exception:
            _local_warning("Telemetry span flush failed; application shutdown continues")
            return False

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:
            _local_warning("Telemetry span shutdown failed; application shutdown continues")


class _FailOpenLogExporter(LogRecordExporter):
    def __init__(self, exporter: LogRecordExporter) -> None:
        self._exporter = exporter

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        try:
            return self._exporter.export(batch)
        except Exception:
            _local_warning("Telemetry log export failed; application processing continues")
            return LogRecordExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 10_000) -> bool:
        try:
            return self._exporter.force_flush(timeout_millis)
        except Exception:
            _local_warning("Telemetry log flush failed; application shutdown continues")
            return False

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:
            _local_warning("Telemetry log shutdown failed; application shutdown continues")


class TelemetryRuntime:
    def __init__(
        self,
        *,
        enabled: bool,
        tracer_provider: TracerProvider | None = None,
        logger_provider: LoggerProvider | None = None,
        logging_handler: logging.Handler | None = None,
    ) -> None:
        self.enabled = enabled
        self._tracer_provider = tracer_provider
        self._logger_provider = logger_provider
        self._logging_handler = logging_handler
        self._tracer = (
            tracer_provider.get_tracer("mvision") if tracer_provider is not None else None
        )
        self._propagator = TraceContextTextMapPropagator()
        self._shutdown = False
        self._lock = threading.Lock()
        self._middleware_installed = False

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
        context: Context | None = None,
        start_time: int | None = None,
    ) -> AbstractContextManager[Span]:
        allowed = name in SPAN_NAMES or (
            name.startswith("live.native.")
            and name == native_span_name(name.removeprefix("live.native."))
        )
        if not self.enabled or self._tracer is None or not allowed:
            return nullcontext(trace.NonRecordingSpan(trace.INVALID_SPAN_CONTEXT))
        return self._tracer.start_as_current_span(
            name,
            attributes=sanitize_attributes(attributes or {}),
            context=context,
            start_time=start_time,
            record_exception=False,
            set_status_on_exception=False,
        )

    def context_from_headers(self, traceparent: str, tracestate: str | None) -> Context:
        if not self.enabled:
            return Context()
        validate_trace_context(traceparent, tracestate)
        carrier = {"traceparent": traceparent}
        if tracestate is not None:
            carrier["tracestate"] = tracestate
        return self._propagator.extract(carrier)

    def record_span(
        self,
        name: str,
        *,
        start_time: int,
        end_time: int,
        attributes: Mapping[str, object] | None = None,
        context: Context | None = None,
        error_code: str | None = None,
    ) -> None:
        if not self.enabled or self._tracer is None:
            return
        operation = name.removeprefix("live.native.")
        if name not in SPAN_NAMES and name != native_span_name(operation):
            return
        span = self._tracer.start_span(
            name,
            context=context,
            attributes=sanitize_attributes(attributes or {}),
            start_time=start_time,
        )
        if error_code is not None:
            span.set_attribute("error_code", error_code)
            span.set_status(Status(StatusCode.ERROR, error_code))
        span.end(end_time=end_time)

    def trace_headers(self) -> tuple[str, str | None]:
        if not self.enabled:
            return "", None
        carrier: dict[str, str] = {}
        self._propagator.inject(carrier)
        return carrier.get("traceparent", ""), carrier.get("tracestate")

    def install_http_middleware(self, app: object) -> None:
        if self._middleware_installed:
            return
        add_middleware = getattr(app, "add_middleware")
        add_middleware(_TelemetryMiddleware, runtime=self)
        self._middleware_installed = True

    def force_flush(self, timeout_millis: int) -> bool:
        if not self.enabled:
            return True
        deadline = time.monotonic() + max(timeout_millis, 0) / 1_000
        results: list[bool] = []
        for provider in (self._tracer_provider, self._logger_provider):
            if provider is None:
                continue
            remaining = max(0, int((deadline - time.monotonic()) * 1_000))
            try:
                results.append(provider.force_flush(remaining))
            except Exception:
                _local_warning("Telemetry flush failed; application shutdown continues")
                results.append(False)
        return all(results)

    def shutdown(self, timeout_millis: int) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self.force_flush(timeout_millis)
        if self._logging_handler is not None:
            logging.getLogger().removeHandler(self._logging_handler)
        for provider in (self._logger_provider, self._tracer_provider):
            if provider is None:
                continue
            try:
                provider.shutdown()
            except Exception:
                _local_warning("Telemetry shutdown failed; application shutdown continues")


def configure_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    log_exporter: LogRecordExporter | None = None,
) -> TelemetryRuntime:
    if not settings.otel_enabled:
        return TelemetryRuntime(enabled=False)

    try:
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": settings.otel_service_version,
                "deployment.environment": settings.otel_deployment_environment,
                "service.instance.id": settings.otel_service_instance_id,
            }
        )
        timeout = settings.otel_export_timeout_seconds
        endpoint = settings.otel_exporter_otlp_endpoint
        selected_span_exporter = span_exporter or OTLPSpanExporter(
            endpoint=endpoint, insecure=endpoint.startswith("http://"), timeout=timeout
        )
        selected_log_exporter = log_exporter or OTLPLogExporter(
            endpoint=endpoint, insecure=endpoint.startswith("http://"), timeout=timeout
        )
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                _FailOpenSpanExporter(selected_span_exporter),
                max_queue_size=settings.otel_bsp_max_queue_size,
                max_export_batch_size=settings.otel_bsp_max_export_batch_size,
                schedule_delay_millis=settings.otel_bsp_schedule_delay_millis,
                export_timeout_millis=timeout * 1_000,
            )
        )
        logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                _FailOpenLogExporter(selected_log_exporter),
                max_queue_size=settings.otel_bsp_max_queue_size,
                max_export_batch_size=settings.otel_bsp_max_export_batch_size,
                schedule_delay_millis=settings.otel_bsp_schedule_delay_millis,
                export_timeout_millis=timeout * 1_000,
            )
        )
        handler = _SafeLoggingHandler(logger_provider)
        logging.getLogger().addHandler(handler)
        return TelemetryRuntime(
            enabled=True,
            tracer_provider=tracer_provider,
            logger_provider=logger_provider,
            logging_handler=handler,
        )
    except Exception:
        _local_warning("Telemetry configuration failed; application startup continues")
        return TelemetryRuntime(enabled=False)
