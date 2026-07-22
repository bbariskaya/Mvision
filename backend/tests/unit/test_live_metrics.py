from types import SimpleNamespace

import pytest
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry

from app.config import Settings
from app.observability.metrics import REQUIRED_METRIC_NAMES, create_metrics


def _series_count(registry: CollectorRegistry) -> int:
    return sum(len(family.samples) for family in registry.collect())


def test_registry_contains_required_metrics_and_documented_units() -> None:
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    metrics.set("worker_up", 1)
    metrics.observe(
        "native_operation_duration_seconds",
        0.25,
        operation="source_connect",
        status="success",
    )
    payload, content_type = metrics.render_metrics()
    text = payload.decode()

    assert content_type == CONTENT_TYPE_LATEST
    assert REQUIRED_METRIC_NAMES <= set(text.split())
    assert "mvision_native_operation_duration_seconds_bucket" in text
    assert "mvision_native_operation_duration_seconds_sum" in text
    assert "mvision_native_operation_duration_seconds_count" in text


def test_same_registry_returns_one_duplicate_resistant_facade() -> None:
    registry = CollectorRegistry()

    first = create_metrics(registry)
    second = create_metrics(registry)

    assert first is second


def test_dynamic_values_cannot_increase_cardinality_or_leak() -> None:
    registry = CollectorRegistry()
    metrics = create_metrics(registry)
    forbidden = (
        "camera_id",
        "run_id",
        "track_id",
        "face_id",
        "name",
        "uri",
        "host",
        "trace_id",
        "span_id",
    )

    metrics.increment(
        "quality_rejections_total",
        reason="rtsp://alice:secret@camera-0.invalid/live?trace_id=0",
    )
    baseline_series = _series_count(registry)
    for index in range(1, 10_000):
        secret = f"rtsp://alice:secret@camera-{index}.invalid/live?trace_id={index}"
        metrics.increment("quality_rejections_total", reason=secret)

    payload, _ = metrics.render_metrics()
    text = payload.decode()
    assert 'reason="other"' in text
    assert "rtsp://" not in text
    assert "alice" not in text
    assert "secret" not in text
    assert "camera-9999" not in text
    for label_name in forbidden:
        assert f'{label_name}="' not in text
    assert _series_count(registry) == baseline_series


def test_metric_facade_rejects_unknown_metrics_and_label_names() -> None:
    metrics = create_metrics(CollectorRegistry())

    try:
        metrics.increment("not_registered")
    except KeyError as error:
        assert str(error) == "'METRIC_NOT_REGISTERED'"
    else:
        raise AssertionError("unknown metric was accepted")

    try:
        metrics.increment("quality_rejections_total", camera_id="camera-1")
    except ValueError as error:
        assert str(error) == "METRIC_LABELS_INVALID"
    else:
        raise AssertionError("prohibited label was accepted")


@pytest.mark.asyncio
async def test_metrics_endpoint_failure_cannot_stop_worker_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import live_worker_main

    processed: list[bool] = []

    class _Runtime:
        def shutdown(self, timeout_millis: int) -> None:
            pass

    class _Loop:
        def add_signal_handler(self, selected_signal: object, callback: object) -> None:
            pass

    async def process_once(*args: object) -> None:
        processed.append(True)

    def fail_endpoint(*args: object, **kwargs: object) -> None:
        raise OSError("bind failed: secret-host.invalid")

    settings = Settings(_env_file=None, live_enabled=False)
    container = SimpleNamespace(
        live_supervisor=SimpleNamespace(), settings=SimpleNamespace(live_worker_poll_seconds=1)
    )
    monkeypatch.setattr(live_worker_main, "get_settings", lambda: settings)
    monkeypatch.setattr(live_worker_main, "configure_telemetry", lambda selected: _Runtime())
    monkeypatch.setattr(live_worker_main, "get_container", lambda *args: container)
    monkeypatch.setattr(live_worker_main, "start_http_server", fail_endpoint)
    monkeypatch.setattr(live_worker_main, "run_worker", process_once)
    monkeypatch.setattr(live_worker_main.asyncio, "get_running_loop", lambda: _Loop())

    await live_worker_main.main()

    assert processed == [True]
