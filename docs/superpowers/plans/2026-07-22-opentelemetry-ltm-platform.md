# OpenTelemetry and LGTM Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable, self-hosted observability platform that correlates Mvision API, worker, native, database, vector-store, object-store, event, and notification operations through traces, structured logs, bounded metrics, and provisioned Grafana views.

**Architecture:** Python owns OpenTelemetry trace/log export and Prometheus metrics; C++ remains network-free and reports bounded semantic operations through the existing MessagePack protocol. All signals flow through an OpenTelemetry Collector into Tempo, Loki, and Prometheus, while Grafana provisioning, privacy/cardinality tests, backend-failure tests, and an overhead A/B establish a mandatory observability contract for every future phase.

**Tech Stack:** Python 3.12, OpenTelemetry Python 1.44.0, prometheus-client 0.25.0, OTLP gRPC, OpenTelemetry Collector Contrib 0.157.0, Prometheus 3.13.0, Loki 3.7.3, Tempo 3.0.0, Grafana OSS 13.1.0, Docker Compose, pytest.

## Global Constraints

- Implement `docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md` completely.
- Observability is a shared platform contract; every future phase extends it and runs applicable telemetry gates.
- C++ performs no OTLP, HTTP, DNS, or telemetry backend network work.
- Do not create spans per frame, detection, embedding, tracker update, or queue item.
- Metrics and Loki stream labels are enum-only and low-cardinality.
- Never export RTSP URIs/hosts/credentials, person names, face IDs, embeddings, snapshots, signed URLs, raw request/response bodies, or unsanitized native stderr.
- Telemetry failure is fail-open for product work and bounded in memory and shutdown time.
- PostgreSQL, Qdrant, MinIO, model, engine, and existing media volumes are never reset, pruned, or mounted into telemetry services.
- Loki retention is 7 days, Tempo retention is 7 days, and Prometheus retention is 15 days.
- Only Grafana may bind a trusted host interface; Collector, Prometheus, Loki, and Tempo remain internal.
- No commit, amend, push, volume deletion, or destructive cleanup is performed unless the user explicitly requests it.

---

### Task 1: Freeze Dependencies And Shared Telemetry Vocabulary

**Files:**
- Create: `backend/app/observability/__init__.py`
- Create: `backend/app/observability/semantic.py`
- Create: `backend/tests/unit/test_observability_semantic.py`
- Modify: `backend/pyproject.toml`
- Modify: `docs/implementation/live-source-attribution.md`

**Interfaces:**
- Produces `SPAN_NAMES: frozenset[str]`.
- Produces `ALLOWED_ATTRIBUTE_KEYS: frozenset[str]`.
- Produces `sanitize_attributes(values: Mapping[str, object]) -> dict[str, AttributeValue]`.
- Produces exact dependency and image release records used by all later tasks.

- [ ] **Step 1: Record exact upstream artifacts**

Record source URL, release, license, Python 3.12 support, and selected artifact for:

```text
opentelemetry-api==1.44.0
opentelemetry-sdk==1.44.0
opentelemetry-exporter-otlp-proto-grpc==1.44.0
prometheus-client==0.25.0
otel/opentelemetry-collector-contrib:0.157.0
prom/prometheus:v3.13.0
grafana/loki:3.7.3
grafana/tempo:3.0.0
grafana/grafana:13.1.0
```

Resolve each container manifest with `docker buildx imagetools inspect`, record
the linux/amd64 digest, and use that digest in Task 6. If an artifact cannot be
resolved or its license/runtime compatibility fails review, stop before editing
Compose rather than substituting `latest`.

- [ ] **Step 2: Write RED semantic/privacy unit tests**

Assert the exact span-name set from the design, enum-only metric labels, scalar
attribute limits, and rejection of prohibited keys/values:

```python
def test_semantic_attributes_reject_identity_and_uri_data() -> None:
    values = {
        "camera_id": CAMERA_ID,
        "run_id": RUN_ID,
        "state": "ACTIVE",
        "face_id": FACE_ID,
        "name": "Baris",
        "uri": "rtsp://admin:secret@camera.invalid/live?token=x",
    }
    assert sanitize_attributes(values) == {
        "camera_id": CAMERA_ID,
        "run_id": RUN_ID,
        "state": "ACTIVE",
    }
```

- [ ] **Step 3: Verify RED**

Run: `docker exec mvision-live-api pytest -q /app/tests/unit/test_observability_semantic.py`

Expected: collection fails because `app.observability.semantic` does not exist.

- [ ] **Step 4: Add pinned Python dependencies and vocabulary**

Add the exact packages above. Define constant span names, allowed enum values,
maximum 64 attributes, maximum 128-character string values, and denylisted key
fragments `uri`, `host`, `credential`, `password`, `token`, `face`, `name`,
`embedding`, `vector`, `snapshot`, and `signed_url`. `sanitize_attributes()`
keeps only explicitly allowed keys and scalar values; it never recursively
serializes objects or payload dictionaries.

- [ ] **Step 5: Verify GREEN and static checks**

Run:

```bash
docker exec mvision-live-api pytest -q /app/tests/unit/test_observability_semantic.py
docker exec mvision-live-api ruff check /app/app/observability /app/tests/unit/test_observability_semantic.py
docker exec mvision-live-api mypy /app/app/observability
```

Expected: all pass with no prohibited-value serialization.

---

### Task 2: Persist W3C Context Across API-To-Worker Claim

**Files:**
- Create: `backend/alembic/versions/c83f19d4a2e7_live_trace_context.py`
- Modify: `backend/app/infrastructure/database/models.py`
- Modify: `backend/app/infrastructure/database/repositories/live_camera_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/live_run_repository.py`
- Modify: `backend/app/services/live_camera_service.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/tests/unit/test_live_camera_service.py`
- Modify: `backend/tests/unit/test_live_supervisor.py`
- Modify: `backend/tests/integration/persistence/test_live_repositories.py`

**Interfaces:**
- `LiveCameraService.start(camera_id, traceparent, tracestate) -> dict[str, Any]` persists the start-request context with desired state.
- `LiveCameraRun.traceparent: str` and `tracestate: str | None` fence one generation's trace.
- `LiveRunRepository.claim(...)` copies the pending camera context into the new run.
- `LiveSupervisor` consumes persisted context instead of generating an unrelated trace ID.

- [ ] **Step 1: Write RED repository and service tests**

Cover:

```text
camera start commits desired_state plus validated traceparent/tracestate
claim copies that context into generation 1
next explicit start replaces context for generation 2
stop clears pending desired-state context
invalid context is rejected before persistence
```

The integration test must inspect committed rows rather than mocks.

- [ ] **Step 2: Verify RED**

Run:

```bash
docker exec mvision-live-api pytest -q /app/tests/unit/test_live_camera_service.py /app/tests/unit/test_live_supervisor.py
```

Expected: failures show missing persisted context fields and current random
`LiveSupervisor._start_command()` trace creation.

- [ ] **Step 3: Add bounded schema fields and migration**

Add nullable pending context to `LiveCamera` and immutable context to
`LiveCameraRun`:

```text
desired_traceparent VARCHAR(55)
desired_tracestate VARCHAR(512)
traceparent VARCHAR(55) NOT NULL
tracestate VARCHAR(512)
```

Backfill pre-existing run rows with a valid generated traceparent only in the
migration, then set `traceparent` non-null. Set migration `down_revision` to
`b72d4e9a6f13`. Reuse existing strict protocol
validation before writes. Do not store baggage.

- [ ] **Step 4: Propagate context through start, claim, and StartCommand**

The HTTP/controller layer extracts active W3C context through the telemetry
runtime, passes it to `LiveCameraService.start()`, and the repository atomically
writes it with `desired_state=running`. Claim copies it to the run. Supervisor
uses `run.traceparent/run.tracestate` in the native `StartCommand` header.

- [ ] **Step 5: Migrate isolated stores and verify GREEN**

Run migration first against `mergenvision_test`, then execute unit and isolated
persistence tests. Expected: all pass and no production database is targeted by
the test command.

---

### Task 3: Reusable OpenTelemetry Runtime And Process Lifecycle

**Files:**
- Create: `backend/app/observability/telemetry.py`
- Create: `backend/tests/unit/test_live_telemetry.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/worker/live_worker_main.py`
- Modify: `backend/.env.example`

**Interfaces:**
- Produces `configure_telemetry(settings, *, span_exporter=None, log_exporter=None) -> TelemetryRuntime`.
- Produces `TelemetryRuntime.start_span(name, attributes=None, context=None, start_time=None)`.
- Produces `TelemetryRuntime.trace_headers() -> tuple[str, str | None]`.
- Produces idempotent `TelemetryRuntime.force_flush(timeout_millis) -> bool` and `shutdown(timeout_millis) -> None`.
- Produces `TelemetryRuntime.install_http_middleware(app)` with strict W3C extraction and allowlisted attributes.

- [ ] **Step 1: Write RED tests with real in-memory exporters**

Use `InMemorySpanExporter` and `InMemoryLogExporter`; do not mock `Tracer`.
Assert resource attributes, parent/child context, explicit timestamps, active
trace ID injection into logs, disabled no-op behavior, exporter exception
fail-open behavior, and bounded idempotent shutdown.

- [ ] **Step 2: Verify RED**

Run: `docker exec mvision-live-api pytest -q /app/tests/unit/test_live_telemetry.py`

Expected: import failure for the missing runtime.

- [ ] **Step 3: Add exact settings**

Add typed settings and validation:

```text
otel_enabled=false
otel_service_name=mvision-api
otel_service_version=0.1.0
otel_deployment_environment=development
otel_service_instance_id=mvision-api-0
otel_exporter_otlp_endpoint=http://otel-collector:4317
otel_export_timeout_seconds=2
otel_bsp_max_queue_size=2048
otel_bsp_max_export_batch_size=256
otel_bsp_schedule_delay_millis=500
otel_shutdown_timeout_seconds=3
```

Reject batch size above queue size and non-positive timeout/queue values.

- [ ] **Step 4: Implement providers and fail-open exporters**

Build `Resource`, `TracerProvider`, `LoggerProvider`, OTLP gRPC span/log
exporters, `BatchSpanProcessor`, and `BatchLogRecordProcessor`. Keep providers
owned by `TelemetryRuntime`; do not rely on mutable process globals in unit
tests. Install a small ASGI middleware that extracts W3C context and emits only
the three allowlisted camera HTTP operation names. Do not use default FastAPI or
SQLAlchemy auto-instrumentation because their server-address, URL, statement,
and peer attributes violate the application-side privacy boundary.
Exporter/configuration failures emit a sanitized local warning and increment a
telemetry failure metric, but return a no-op/fail-open runtime.

- [ ] **Step 5: Wire API and live-worker lifecycle**

Configure before container/database work. Store runtime on `app.state`, flush
and shut it down in `lifespan` finally. The live worker configures service name
`mvision-live-worker`, flushes during SIGTERM shutdown, and never changes worker
exit status because telemetry flush failed.

- [ ] **Step 6: Verify GREEN**

Run the telemetry tests plus existing API lifespan and worker shutdown tests.
Expected: product return values are byte-for-byte identical with telemetry off
and with in-memory exporters enabled.

---

### Task 4: Shared Prometheus Registry And Metrics Endpoints

**Files:**
- Create: `backend/app/observability/metrics.py`
- Create: `backend/app/presentation/routers/metrics.py`
- Create: `backend/tests/unit/test_live_metrics.py`
- Create: `backend/tests/contract/test_metrics_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/worker/live_worker_main.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces one explicit `CollectorRegistry` per process.
- Produces `render_metrics() -> tuple[bytes, str]` using `generate_latest()` and `CONTENT_TYPE_LATEST`.
- Produces API `GET /metrics` and internal-only live-worker metrics port `9464`.
- Produces exact metric families required by the observability design.

- [ ] **Step 1: Write RED metric and endpoint tests**

Assert required names, documented units, allowed labels, duplicate-registration
resistance, API content type, worker bind address, and absence of camera/run/
track/face/name/URI/host/trace labels. Feed malicious dynamic values and scan
the rendered exposition text.

- [ ] **Step 2: Verify RED**

Run the two new test modules. Expected: missing registry/router failures.

- [ ] **Step 3: Implement bounded metrics**

Create these exact required families:

```text
mvision_live_worker_up
mvision_live_runtime_state
mvision_live_frames_total
mvision_live_frame_age_seconds
mvision_live_reconnects_total
mvision_live_active_tracks
mvision_live_embeddings_total
mvision_live_missing_embeddings_total
mvision_live_quality_rejections_total{reason}
mvision_live_protocol_queue_depth
mvision_live_protocol_dropped_total{type}
mvision_live_identity_decisions_total{outcome}
mvision_live_events_total{type}
mvision_live_event_suppressions_total{reason}
mvision_live_output_frames_total
mvision_live_websocket_dropped_total
mvision_telemetry_queue_depth{signal}
mvision_telemetry_dropped_total{signal,reason}
mvision_telemetry_export_failures_total{signal}
mvision_native_operation_duration_seconds{operation,status}
mvision_live_trace_sampling_total{decision,reason}
```

Add dependency-duration histograms only with enum `dependency` and `outcome`
labels. Every metric constructor uses the shared registry and enum-only label
names from `semantic.py`.

- [ ] **Step 4: Expose API and worker endpoints**

The API route returns generated bytes. The worker starts a Prometheus HTTP
server bound to `0.0.0.0:9464` inside its container; Compose uses `expose`, not
a host port. Endpoint failure is visible but cannot stop media processing.

- [ ] **Step 5: Verify GREEN and cardinality bound**

Generate 10,000 events with changing IDs and assert time-series count remains
constant. Run focused tests, Ruff, mypy, and `git diff --check`.

---

### Task 5: Semantic Traces, Native Spans, And Redacted Logs

**Files:**
- Modify: `backend/app/presentation/controllers/cameras.py`
- Modify: `backend/app/services/live_supervisor.py`
- Modify: `backend/app/services/live_identity_service.py`
- Modify: `backend/app/services/live_event_service.py`
- Modify: `backend/app/infrastructure/vector_store/qdrant_adapter.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Modify: `backend/app/infrastructure/live/native_runner.py`
- Create: `backend/tests/contract/test_telemetry_privacy.py`
- Modify: `backend/tests/unit/test_live_telemetry.py`

**Interfaces:**
- Produces the exact semantic trace tree from HTTP start through notification.
- Converts `NativeOperationEvent` monotonic timestamps to UTC from one run
  `(wall_time_ns, monotonic_ns)` anchor.
- Emits only structured, trace-correlated, sanitized native stderr logs.

- [ ] **Step 1: Write RED trace-tree tests**

Prove one trace contains:

```text
http.camera.start
  -> live.supervisor.claim
     -> live.camera.run
        -> live.native.source_connect
        -> live.native.first_frame
        -> live.identity.resolve
           -> live.qdrant.search
        -> live.snapshot.upload
        -> live.event.commit
        -> live.notification.publish
```

Also prove renewals, reconnect/error status, explicit native duration, no
per-frame spans, and correct behavior across inference exceptions.

- [ ] **Step 2: Write RED end-to-end privacy scan**

Inject userinfo URI, query token, person name, face ID, vector values, JPEG
bytes, object credentials, signed URL, and native stderr containing all of them.
Serialize every exported span/log and rendered metric. Require zero forbidden
plaintext matches and zero dynamic labels.

- [ ] **Step 3: Verify RED**

Run focused telemetry and privacy tests. Expected: missing semantic spans and
unsatisfied correlation tree.

- [ ] **Step 4: Instrument only operation boundaries**

Use exact constant names. IDs may be span attributes after validation but never
metric/Loki labels. Errors set stable `error.type`/`error_code` and span status;
do not record raw exception strings. Instrument `search_batch`, snapshot upload,
event commit, and post-commit notification once per semantic operation.

- [ ] **Step 5: Convert native operations and correlate stderr**

Validate echoed W3C context. Convert monotonic start/end through the run anchor,
create `live.native.{operation}` child spans with explicit times, and reject invalid
or out-of-range operations through existing protocol validation. Pass stderr
through `redact_live_text` before creating a structured log under the active
run context.

- [ ] **Step 6: Verify GREEN and hot-path exclusion**

Run focused tests and inspect graph/diff to confirm no span creation in pad
probes, frame loops, detection loops, embedding loops, or C++ code.

---

### Task 6: Collector, Prometheus, Loki, Tempo, And Compose

**Files:**
- Create: `docker-compose.observability.yml`
- Create: `configs/observability/otel-collector.yml`
- Create: `configs/observability/prometheus.yml`
- Create: `configs/observability/loki.yml`
- Create: `configs/observability/tempo.yml`
- Create: `backend/tests/unit/test_observability_config_contract.py`
- Create: `docker-compose.live.yml`
- Modify: `backend/.env.example`

**Interfaces:**
- Collector receives OTLP gRPC/HTTP, exports traces to Tempo and logs to Loki's native OTLP endpoint, and exposes span/service-graph metrics to Prometheus.
- Prometheus scrapes API `/metrics`, worker `:9464/metrics`, Collector, Loki, and Tempo.
- Dedicated telemetry volumes never overlap application volumes.

- [ ] **Step 1: Write RED YAML/Compose contract tests**

Parse rendered Compose and all YAML. Assert digest-only images, health checks,
internal ports, memory limiter before batch, bounded sending queues, retries,
tail-sampling rules, native Loki OTLP, 7d/7d/15d retention, dedicated volumes,
and no committed Grafana default password.

- [ ] **Step 2: Verify RED**

Run: `docker exec mvision-live-api pytest -q /app/tests/unit/test_observability_config_contract.py`

Expected: missing files.

- [ ] **Step 3: Add Collector pipelines**

Configure OTLP receivers; memory limiter; attribute allowlist/filter; batch;
tail sampling that retains errors, reconnects, stable slow spans and 10 percent
ordinary success; Tempo OTLP exporter; Loki native OTLP HTTP exporter; span
metrics and service graph connectors; bounded queue/retry settings; and
Collector internal telemetry.

- [ ] **Step 4: Add storage backends and scrape configuration**

Configure single-node local-filesystem Loki with Compactor retention, Tempo
single-binary with OTLP and metrics-generator/service graphs, and Prometheus
with 15-day command retention. Use the reviewed linux/amd64 digests from Task 1.

- [ ] **Step 5: Add non-destructive Compose wiring**

Add dedicated `otel_data`, `prometheus_data`, `loki_data`, `tempo_data`, and
`grafana_data` volumes. Do not expose backend ports to the host. Pass OTEL
settings to API/live worker, add worker internal metrics exposure, and preserve
existing application service/volume definitions.

- [ ] **Step 6: Verify GREEN before startup**

Run Compose config, config contract tests, and image reference scans. Do not run
`down -v`, `prune`, or recreate application stores.

---

### Task 7: Grafana Provisioning, Correlations, Dashboards, And Alerts

**Files:**
- Create: `configs/observability/grafana/provisioning/datasources/mvision.yml`
- Create: `configs/observability/grafana/provisioning/dashboards/mvision.yml`
- Create: `configs/observability/grafana/provisioning/alerting/mvision-live.yml`
- Create: `configs/observability/grafana/dashboards/live-camera-operations.json`
- Create: `configs/observability/grafana/dashboards/recognition-quality.json`
- Create: `configs/observability/grafana/dashboards/protocol-backpressure.json`
- Create: `configs/observability/grafana/dashboards/dependencies.json`
- Create: `configs/observability/grafana/dashboards/telemetry-health.json`
- Modify: `backend/tests/unit/test_observability_config_contract.py`

**Interfaces:**
- Fixed datasource UIDs: `prometheus`, `loki`, `tempo`.
- Fixed dashboard UIDs and version-controlled queries.
- Bidirectional trace/log links, trace-to-metrics, service graph, and node graph.

- [ ] **Step 1: Extend RED provisioning tests**

Assert three datasource UIDs, five exact dashboard titles/UIDs, non-empty real
queries, cross-datasource correlation configuration, no dynamic/high-cardinality
dashboard variables, and all nine required alert categories.

- [ ] **Step 2: Verify RED**

Expected: missing provisioning/dashboard files.

- [ ] **Step 3: Provision datasources and correlations**

Provision Prometheus, Loki, and Tempo by internal URL. Tempo links to Loki with
service name plus trace ID query and to Prometheus span metrics. Loki derived
fields link structured trace IDs to Tempo without making trace ID a Loki label.

- [ ] **Step 4: Add five operational dashboards**

Each dashboard uses only provisioned datasources and bounded variables such as
environment, service, state, outcome, operation, and stable error code. Include
the panels enumerated in the design; no panel may depend on camera/name/face/
track/URI labels.

- [ ] **Step 5: Add alert rules and verify GREEN**

Provision rules for worker absence, stale active frames, reconnect storms,
protocol/telemetry drops, embedding coverage regression, output stall,
event/snapshot persistence failure, telemetry backend/export failure, and disk
budget pressure. Run config tests and Grafana provisioning validation.

---

### Task 8: Reusable Acceptance, Fault Isolation, Retention, And Overhead

**Files:**
- Create: `backend/scripts/live_observability_acceptance.py`
- Create: `backend/tests/integration/live/test_live_observability.py`
- Create: `backend/tests/integration/live/test_live_telemetry_faults.py`
- Create: `docs/implementation/observability-extension-contract.md`
- Modify: `docs/implementation/CURRENT_SPRINT.md`
- Modify: `README.md`

**Interfaces:**
- Produces a machine-readable acceptance JSON with verdicts for trace continuity, logs, metrics, dashboards, correlations, privacy, cardinality, failure isolation, retention, and overhead.
- Produces a reusable checklist/template required by every future phase.

- [ ] **Step 1: Write RED integration tests**

Query real Collector, Prometheus, Loki, Tempo, and Grafana APIs. Require one
camera run trace, correlated logs, application/native/Collector metrics, five
non-empty dashboards, four correlation directions, and service graph data.
Mocks and screenshots do not satisfy these tests.

- [ ] **Step 2: Add fault scenarios**

Stop Collector, Loki, Tempo, and Prometheus separately. During every outage,
measure camera state, decoded/inference/output counters, telemetry queue/drop/
failure counters, process memory, and recovery after restart. Product work must
continue unless a media dependency independently fails.

- [ ] **Step 3: Add privacy/cardinality and retention scenarios**

Scan backend APIs and stored telemetry for prohibited values. Compare series/
stream cardinality before and after changing camera/run/track/identity IDs.
Use disposable telemetry volumes and shortened test retention to prove expiry,
then restore 7d/7d/15d configuration. Never alter application retention.

- [ ] **Step 4: Add deterministic overhead A/B**

Run the same fixed RTSP window with telemetry disabled and enabled. Capture
processed FPS, evidence count, output frames/drops, CPU, RSS, GPU memory, and
sample count. Require processed-FPS degradation at or below 3 percent and zero
telemetry-induced evidence/output drops.

- [ ] **Step 5: Add the future-phase extension contract**

Document the mandatory per-phase sequence:

```text
define semantic spans/logs/metrics
write privacy/cardinality tests
extend dashboards/alerts
run backend-outage fail-open test
run same-input overhead comparison
record PASS/PARTIAL/BLOCKED/NOT_TESTED evidence
```

Every future implementation plan must link this contract and include its own
observability completion task.

- [ ] **Step 6: Run full acceptance and regression**

Run unit/contract tests, isolated integration tests, native CTest, Ruff, mypy,
Compose config checks, observability acceptance, fault tests, and
`git diff --check`. Record exact commands and raw report paths in
`CURRENT_SPRINT.md`; leave 24-hour soak `NOT_TESTED` until actually completed.
