# Live Operations Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a balanced live-operations Grafana dashboard with meaningful recognition-yield metrics, compact anomaly indicators, recent error traces, correlated logs, and a safe end-to-end smoke check.

**Architecture:** The existing native metrics event remains the source of cumulative counters. `LiveSupervisor` converts selected counters to process-local Prometheus deltas, Grafana derives bounded ratios with PromQL, and a small observability CLI emits one privacy-safe correlated error span/log through the same OTLP path as production. Provisioned Tempo/Loki correlations provide bidirectional navigation without making trace IDs labels.

**Tech Stack:** Python 3.12, prometheus-client 0.25.0, OpenTelemetry Python 1.44.0, Prometheus 3.13.0, Loki 3.7.3, Tempo 3.0.0, Grafana OSS 13.1.0, pytest, Docker Compose.

## Global Constraints

- Do not add per-frame spans or per-object logs.
- Do not use camera ID, run ID, face ID, track ID, trace ID, URI, host, or person data as a Prometheus or Loki stream label.
- Only stable `error_code` values may describe failures in exported telemetry.
- The observability path must fail open and must not interrupt media processing.
- Keep Collector, Prometheus, Loki, and Tempo internal; only Grafana binds the trusted host interface.
- Do not create commits unless the user explicitly requests one.

---

### Task 1: Recognition-Yield Prometheus Counters

**Files:**
- Modify: `backend/app/observability/metrics.py:17-147`
- Modify: `backend/app/services/live_supervisor.py:382-412`
- Modify: `backend/tests/unit/test_live_supervisor.py`

**Interfaces:**
- Consumes: native `MetricsEvent.counters` keys `tracked_objects`, `eligible_objects`, and `embedding_cosine_samples`.
- Produces: unlabeled counters `tracked_objects_total`, `eligible_objects_total`, and `embedding_cosine_samples_total` in `MvisionMetrics`.

- [ ] **Step 1: Write the failing supervisor metric test**

Add a runner that emits two cumulative snapshots and verifies exact deltas, including the existing fields:

```python
class _RecognitionMetricsRunner:
    async def run(self, start, on_event, commands):
        for sequence, counters in (
            (10, {
                "decoded_frames": 100,
                "tracked_objects": 30,
                "eligible_objects": 20,
                "embedding_count": 18,
                "missing_embeddings": 2,
                "embedding_cosine_samples": 12,
                "dropped_events": 0,
            }),
            (11, {
                "decoded_frames": 140,
                "tracked_objects": 44,
                "eligible_objects": 29,
                "embedding_count": 26,
                "missing_embeddings": 3,
                "embedding_cosine_samples": 18,
                "dropped_events": 0,
            }),
        ):
            result = on_event(MetricsEvent(_header("metrics", sequence), counters, {}))
            if asyncio.iscoroutine(result):
                await result
        stopped = StoppedEvent(_header("stopped", 12), 140, 44, 0, True, "operator")
        result = on_event(stopped)
        if asyncio.iscoroutine(result):
            await result
        return stopped


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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend && uv run pytest tests/unit/test_live_supervisor.py::test_native_recognition_counters_are_exported_as_exact_prometheus_deltas -q`

Expected: FAIL because the three new metric names are absent.

- [ ] **Step 3: Register the three unlabeled counters**

Add these names to `REQUIRED_METRIC_NAMES` and definitions to `_DEFINITIONS`:

```python
"mvision_live_tracked_objects_total",
"mvision_live_eligible_objects_total",
"mvision_live_embedding_cosine_samples_total",
```

```python
"tracked_objects_total": _Definition(
    "mvision_live_tracked_objects_total", Counter, "Tracked live objects."
),
"eligible_objects_total": _Definition(
    "mvision_live_eligible_objects_total", Counter, "Embedding-eligible live objects."
),
"embedding_cosine_samples_total": _Definition(
    "mvision_live_embedding_cosine_samples_total",
    Counter,
    "Consecutive embedding cosine samples.",
),
```

- [ ] **Step 4: Extend the existing cumulative-to-delta mapping**

Use this exact mapping in `LiveSupervisor._persist_metrics`:

```python
for source, target in (
    ("decoded_frames", "frames_total"),
    ("tracked_objects", "tracked_objects_total"),
    ("eligible_objects", "eligible_objects_total"),
    ("embedding_count", "embeddings_total"),
    ("missing_embeddings", "missing_embeddings_total"),
    ("embedding_cosine_samples", "embedding_cosine_samples_total"),
):
```

- [ ] **Step 5: Run focused metric tests and verify GREEN**

Run: `cd backend && uv run pytest tests/unit/test_live_supervisor.py tests/unit/test_observability_semantic.py tests/contract/test_telemetry_privacy.py -q`

Expected: all selected tests PASS.

---

### Task 2: Balanced Metrics And Error Investigation Dashboard

**Files:**
- Modify: `configs/observability/grafana/dashboards/live-camera-operations.json`
- Modify: `backend/tests/unit/test_observability_config_contract.py:126-169`

**Interfaces:**
- Consumes: Task 1 Prometheus counters; fixed datasource UIDs `prometheus`, `tempo`, and `loki`.
- Produces: dashboard version 3 with operational stats, recognition-yield trends, anomaly stats, error TraceQL, and correlated LogQL.

- [ ] **Step 1: Write failing dashboard semantic assertions**

After loading the dashboard in `test_grafana_datasources_dashboards_and_alerts_are_fully_provisioned`, add:

```python
live = json.loads(
    (grafana / "dashboards/live-camera-operations.json").read_text()
)
panels = {panel["title"]: panel for panel in live["panels"]}
assert live["version"] == 3
assert {
    "Worker Up",
    "Runtime State",
    "Current FPS",
    "Face Load / 100 Frames",
    "Embedding Coverage",
    "Pipeline Throughput",
    "Recognition Yield",
    "Missing Embeddings",
    "Native Operation p95",
    "Reconnects (5m)",
    "Protocol Drops (5m)",
    "Telemetry Failures (5m)",
    "Recent Error Traces",
    "Correlated Live Logs",
} == set(panels)
assert panels["Recent Error Traces"]["datasource"]["uid"] == "tempo"
assert panels["Correlated Live Logs"]["datasource"]["uid"] == "loki"
assert "status = error" in panels["Recent Error Traces"]["targets"][0]["query"]
assert "trace_id" in panels["Correlated Live Logs"]["targets"][0]["expr"]
assert "Events and Output" not in panels
```

- [ ] **Step 2: Run the config contract and verify RED**

Run: `cd backend && uv run pytest tests/unit/test_observability_config_contract.py -q`

Expected: FAIL because dashboard v2 has the old eight panels.

- [ ] **Step 3: Replace dashboard v2 with dashboard v3**

Use fixed datasource UIDs and these exact PromQL expressions:

```promql
sum(rate(mvision_live_frames_total{job="mvision-live-worker"}[1m]))
100 * sum(rate(mvision_live_tracked_objects_total{job="mvision-live-worker"}[5m])) / clamp_min(sum(rate(mvision_live_frames_total{job="mvision-live-worker"}[5m])), 0.001)
100 * sum(rate(mvision_live_embeddings_total{job="mvision-live-worker"}[5m])) / clamp_min(sum(rate(mvision_live_eligible_objects_total{job="mvision-live-worker"}[5m])), 0.001)
sum(rate(mvision_live_tracked_objects_total{job="mvision-live-worker"}[5m]))
sum(rate(mvision_live_eligible_objects_total{job="mvision-live-worker"}[5m]))
sum(rate(mvision_live_embeddings_total{job="mvision-live-worker"}[5m]))
100 * sum(rate(mvision_live_missing_embeddings_total{job="mvision-live-worker"}[5m])) / clamp_min(sum(rate(mvision_live_eligible_objects_total{job="mvision-live-worker"}[5m])), 0.001)
increase(mvision_live_reconnects_total{job="mvision-live-worker"}[5m])
sum(increase(mvision_live_protocol_dropped_total{job="mvision-live-worker"}[5m]))
sum(increase(mvision_telemetry_export_failures_total[5m]))
```

`Pipeline Throughput` overlays decoded, tracked, eligible, and embedding rates.
`Recognition Yield` shows embedding coverage and cosine-sample coverage as
percentages. Anomaly panels are `stat` visualizations with green zero and
warning/critical positive thresholds. `Recent Error Traces` is a Tempo traces
panel with:

```traceql
{ resource.service.name =~ "mvision-(api|live-worker)" && status = error }
```

`Correlated Live Logs` is a Loki logs panel with:

```logql
{service_name=~"mvision-(api|live-worker)"} | trace_id != ``
```

- [ ] **Step 4: Run the config contract and validate dashboard JSON**

Run: `cd backend && uv run pytest tests/unit/test_observability_config_contract.py -q`

Expected: PASS.

Run: `python3 -m json.tool configs/observability/grafana/dashboards/live-camera-operations.json >/dev/null`

Expected: exit code 0.

---

### Task 3: Privacy-Safe Correlated Error Smoke Producer

**Files:**
- Create: `backend/app/observability/smoke.py`
- Modify: `backend/app/observability/telemetry.py:50-64`
- Create: `backend/tests/unit/test_observability_smoke.py`

**Interfaces:**
- Consumes: `TelemetryRuntime`, existing OTLP settings, and safe logging handler.
- Produces: `emit_error_smoke(runtime: TelemetryRuntime) -> str` returning a 32-character trace ID and CLI exit code 0 only after a successful bounded flush.

- [ ] **Step 1: Write the failing correlated smoke unit test**

```python
import logging

from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.observability.smoke import emit_error_smoke
from app.observability.telemetry import configure_telemetry


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
        assert span.status.is_ok is False
        assert span.attributes["error_code"] == "OBSERVABILITY_SMOKE_TEST"
        assert record.attributes["error_code"] == "OBSERVABILITY_SMOKE_TEST"
        assert record.body == "Observability smoke test"
    finally:
        runtime.shutdown(1_000)
        logging.getLogger().handlers = [
            handler
            for handler in logging.getLogger().handlers
            if handler.__class__.__name__ != "_SafeLoggingHandler"
        ]
```

- [ ] **Step 2: Run the smoke unit test and verify RED**

Run: `cd backend && uv run pytest tests/unit/test_observability_smoke.py -q`

Expected: collection FAIL because `app.observability.smoke` does not exist.

- [ ] **Step 3: Add the safe log template**

Add `"Observability smoke test"` to `_SafeLoggingHandler._SAFE_MESSAGES`.

- [ ] **Step 4: Implement the smoke producer and CLI**

```python
import logging

from opentelemetry.trace import Status, StatusCode

from app.config import get_settings
from app.observability.telemetry import TelemetryRuntime, configure_telemetry

ERROR_CODE = "OBSERVABILITY_SMOKE_TEST"
logger = logging.getLogger(__name__)


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
        if not runtime.force_flush(int(settings.otel_shutdown_timeout_seconds * 1_000)):
            return 3
        print(trace_id)
        return 0
    finally:
        runtime.shutdown(int(settings.otel_shutdown_timeout_seconds * 1_000))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run smoke, telemetry, and privacy tests**

Run: `cd backend && uv run pytest tests/unit/test_observability_smoke.py tests/unit/test_live_telemetry.py tests/contract/test_telemetry_privacy.py -q`

Expected: all selected tests PASS and no prohibited plaintext appears.

---

### Task 4: Real LGTM Acceptance And Operator Instructions

**Files:**
- Create: `backend/scripts/verify_live_observability.py`
- Create: `backend/scripts/test_verify_live_observability.py`
- Modify: `docs/implementation/CURRENT_SPRINT.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Grafana URL, Grafana credentials from environment, dashboard UID, and smoke trace ID.
- Produces: a nonzero-exit acceptance CLI that verifies Prometheus values, Tempo error trace discovery, Loki trace-correlated log discovery, and dashboard provisioning.

- [ ] **Step 1: Write failing response-parsing tests**

Test pure helpers against representative Prometheus, Tempo, Loki, and Grafana JSON. Require:

```python
assert prometheus_scalar(prometheus_payload) > 0
assert tempo_has_trace(tempo_payload, trace_id)
assert loki_has_trace(loki_payload, trace_id)
assert dashboard_has_panels(dashboard_payload, {
    "Embedding Coverage", "Recent Error Traces", "Correlated Live Logs"
})
```

Also assert malformed payloads and absent trace IDs return false or raise the
stable `OBSERVABILITY_ACCEPTANCE_FAILED` error without printing response bodies.

- [ ] **Step 2: Run parser tests and verify RED**

Run: `cd backend && uv run pytest scripts/test_verify_live_observability.py -q`

Expected: collection FAIL because the verifier module does not exist.

- [ ] **Step 3: Implement bounded Grafana datasource-proxy checks**

Use `httpx.Client(timeout=5.0)` and HTTP Basic auth from
`GRAFANA_USER`/`GRAFANA_PASSWORD`. Query:

```text
GET /api/dashboards/uid/mvision-live-operations
GET /api/datasources/proxy/uid/prometheus/api/v1/query?query=sum(rate(mvision_live_frames_total{job="mvision-live-worker"}[1m]))
GET /api/datasources/proxy/uid/tempo/api/search?q={resource.service.name="mvision-live-worker"&&span.error_code="OBSERVABILITY_SMOKE_TEST"}
GET /api/datasources/proxy/uid/loki/loki/api/v1/query_range?query={service_name="mvision-live-worker"}|trace_id=`TRACE_ID`
```

URL-encode every query through `httpx` `params`, cap response handling at 1 MiB,
never print response bodies, and print only pass/fail signal names plus the safe
trace ID.

- [ ] **Step 4: Run verifier unit tests and quality checks**

Run: `cd backend && uv run pytest scripts/test_verify_live_observability.py -q`

Expected: PASS.

Run: `cd backend && uv run ruff check app/observability scripts/verify_live_observability.py scripts/test_verify_live_observability.py`

Expected: PASS.

- [ ] **Step 5: Restart only the services needed to load telemetry and dashboard changes**

Use the existing Compose project/environment. Recreate API and live worker with
the observability override so immutable telemetry environment is present; do not
restart PostgreSQL, Qdrant, MinIO, or GPU services unrelated to the live worker.
Confirm the camera returns to `ACTIVE` before continuing.

- [ ] **Step 6: Emit and verify one real correlated smoke record**

Inside the recreated worker container run:

```bash
python3 -m app.observability.smoke
```

Capture the printed trace ID, then run from the host with credentials supplied
only through environment variables:

```bash
cd backend && uv run python scripts/verify_live_observability.py --trace-id "$TRACE_ID" --grafana-url http://127.0.0.1:3001
```

Expected output contains PASS for dashboard, Prometheus, Tempo, and Loki. It
must not contain URI, camera, run, person, credential, response-body, or exception
plaintext.

- [ ] **Step 7: Verify UI correlation without causing a product failure**

Open `Live Camera Operations`, set the range to last 15 minutes, select the
`OBSERVABILITY_SMOKE_TEST` row in `Recent Error Traces`, and confirm `Logs for
this span` returns the correlated safe log. In `Correlated Live Logs`, select the
TraceID derived field and confirm it opens the same Tempo trace.

- [ ] **Step 8: Update operator documentation and run the complete verification set**

Document the tunnel, dashboard URL, smoke command, verifier command, expected
safe error code, and the rule that smoke tests never crash media processing.

Run: `cd backend && uv run pytest tests/unit/test_live_supervisor.py tests/unit/test_live_telemetry.py tests/unit/test_observability_config_contract.py tests/unit/test_observability_semantic.py tests/unit/test_observability_smoke.py tests/contract/test_telemetry_privacy.py scripts/test_verify_live_observability.py -q`

Expected: all selected tests PASS.

Run: `git diff --check`

Expected: no whitespace errors.
