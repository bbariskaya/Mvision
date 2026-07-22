import asyncio
import logging

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry

from app.config import Settings
from app.infrastructure.live.native_runner import NativeLiveRunner
from app.observability.metrics import create_metrics
from app.observability.telemetry import configure_telemetry


@pytest.mark.asyncio
async def test_exported_telemetry_contains_no_prohibited_plaintext() -> None:
    span_exporter = InMemorySpanExporter()
    log_exporter = InMemoryLogRecordExporter()
    runtime = configure_telemetry(
        Settings(_env_file=None, otel_enabled=True, otel_bsp_schedule_delay_millis=10),
        span_exporter=span_exporter,
        log_exporter=log_exporter,
    )
    metrics = create_metrics(CollectorRegistry())
    forbidden = (
        "rtsp://alice:secret@camera.invalid/live?token=hidden",
        "Ada Secretperson",
        "face-secret-123",
        "0.123456789,0.987654321",
        "JPEG-SECRET-BYTES",
        "minio-secret-key",
        "signed.example/object?signature=hidden",
    )
    malicious = " | ".join(forbidden)

    with runtime.start_span(
        "live.camera.run",
        {
            "camera_id": forbidden[0],
            "run_id": forbidden[2],
            "reason": malicious,
            "error_code": malicious,
        },
    ):
        logging.getLogger("app.infrastructure.live.native_runner").warning(malicious)
        reader = asyncio.StreamReader()
        reader.feed_data((malicious + "\n").encode())
        reader.feed_eof()
        await NativeLiveRunner._drain_stderr(reader)

    for index in range(1_000):
        metrics.increment("quality_rejections_total", reason=f"{malicious}-{index}")
    assert runtime.force_flush(1_000)

    exported = repr(
        [
            (span.name, dict(span.attributes or {}))
            for span in span_exporter.get_finished_spans()
        ]
        + [
            (record.log_record.body, dict(record.log_record.attributes or {}))
            for record in log_exporter.get_finished_logs()
        ]
    )
    metric_text = metrics.render_metrics()[0].decode()
    for value in forbidden:
        assert value not in exported
        assert value not in metric_text
    assert "Application diagnostic" in exported
    assert "Native live worker diagnostic" in exported
    runtime.shutdown(1_000)
