# OpenTelemetry and LGTM Observability Design

## Status and Scope

This document extends the approved single-camera livestream design. The user
made end-to-end logs, traces, metrics, Grafana dashboards, and their self-hosted
backends a required first-milestone acceptance gate on 2026-07-21.

The required stack is OpenTelemetry Python instrumentation, OpenTelemetry
Collector Contrib, Prometheus, Loki, Tempo, and Grafana. The C++ worker never
exports telemetry over the network. It emits bounded semantic events through
the existing MessagePack channel; Python owns OTLP export, retry, redaction,
sampling, and Collector connectivity.

This requirement does not permit telemetry to block the media pipeline, add
network work to a pad probe, or expose recognition secrets or personal data.

## Goals

- Correlate one camera operation across HTTP, PostgreSQL, supervisor, native
  lifecycle, Qdrant, object storage, durable event commit, and notification.
- Provide actionable metrics, sanitized structured logs, and distributed
  traces from provisioned Grafana data sources and dashboards.
- Preserve low-cardinality metrics and Loki streams.
- Keep telemetry queues bounded and runtime behavior fail-open.
- Prove observability overhead and failure isolation with real GPU/runtime
  acceptance, not unit mocks.
- Use only self-hosted components in the required path.
- Establish observability as a reusable platform contract for every future
  Mvision phase, not a livestream-only add-on.

## Mandatory Contract For Future Phases

Every future phase, service, worker, protocol, dependency integration, and
background job must define its telemetry contract before implementation. A
phase is not complete when only its product behavior works.

Each phase must add and verify, as applicable:

- low-cardinality semantic spans at operation boundaries, never per-frame or
  per-item hot-loop spans;
- structured, trace-correlated, application-redacted logs;
- bounded metrics with enum-only labels and documented units;
- W3C context propagation across HTTP, process, MessagePack, and asynchronous
  boundaries;
- dashboard and alert coverage for its operational failure modes;
- privacy/cardinality scans covering all newly introduced values;
- Collector/backend outage tests proving product work remains fail-open;
- enabled-versus-disabled overhead evidence on the same deterministic input;
- an update to the shared telemetry semantic-convention and source-attribution
  ledgers.

The reusable Python telemetry runtime, Collector path, datasource UIDs,
redaction policy, resource attributes, and acceptance-report format are shared
platform interfaces. Future phases extend these interfaces instead of creating
parallel exporters, custom telemetry backends, dynamic naming schemes, or
phase-specific Grafana configuration outside version control.

Every implementation plan must contain an explicit observability task and an
observability completion gate. Any gate that cannot be exercised in that phase
is recorded as `NOT_TESTED` with a reason; it is never silently omitted or
promoted by mocked evidence.

## Non-Goals

- Per-frame, per-detection, per-embedding, or per-track spans.
- Person, identity, camera URI, or host dimensions in telemetry.
- Direct OTLP export from C++.
- A hosted Grafana, commercial APM, managed collector, or paid alert channel.
- Long-term multi-node observability storage or high-availability backends in
  the first single-camera milestone.
- Continuous profiling. Pyroscope remains a future evaluation.

## Architecture

```text
FastAPI / supervisor / repositories
  | OpenTelemetry Python SDK: traces + logs over OTLP
  | Prometheus client: bounded low-cardinality /metrics
  v
OpenTelemetry Collector Contrib
  |-- OTLP traces --> Tempo
  |-- OTLP logs ----> Loki native OTLP HTTP endpoint
  |-- Prometheus receiver scrapes /metrics
  |-- span metrics --> Prometheus
  v
Grafana: provisioned Prometheus + Loki + Tempo data sources and dashboards

C++ DeepStream worker
  | bounded semantic state/metrics/native-operation events
  | redacted stderr
  v
Python supervisor -> active run trace -> Collector
```

Applications send telemetry only to the Collector. Collector pipelines use a
memory limiter, bounded sending queues, batch processing, attribute filtering,
and retries. Collector or backend unavailability increments telemetry-drop or
export-failure metrics but cannot fail a camera run.

## Trace Context and Native Boundary

The live protocol common header gains:

```text
traceparent: W3C trace-parent string
tracestate: optional bounded W3C trace-state string
```

`StartCommand` carries the active supervisor run context. Native events echo
the same validated context. A new bounded `NativeOperationEvent` describes a
completed operation without exporting OTLP from C++:

```text
operation: enum
started_monotonic_ns: uint64
ended_monotonic_ns: uint64
status: ok|error
error_code: optional stable enum
attributes: max 16 allowlisted enum/numeric entries
```

Allowed native operations are:

```text
source_connect, first_frame, reconnect, graph_rebuild,
inference_window, output_start, output_stop, teardown
```

The supervisor converts each record to a span under `mvision.live.camera.run`
using explicit timestamps. It does not create spans for frames, detections, or
individual embeddings. Existing state, evidence, metrics, failure, and stopped
events remain authoritative product protocol events; native operation records
exist only for bounded observability.

Malformed trace context, unknown operations, non-monotonic timestamps, excess
attributes, and high-cardinality attribute names are rejected by both Python
and C++ codecs.

## Instrumentation Model

Required low-cardinality span names:

```text
http.camera.register
http.camera.start
http.camera.stop
live.supervisor.claim
live.supervisor.lease_renew
live.camera.run
live.native.<operation-enum>
live.identity.resolve
live.qdrant.search
live.snapshot.upload
live.event.commit
live.notification.publish
```

Required resource attributes are `service.name`, `service.version`,
`deployment.environment`, and `service.instance.id`. Span/log attributes may
include technical `camera_id`, `run_id`, `generation`, enum state, enum outcome,
queue type, operation, and stable error code. IDs are attributes or structured
metadata, never Prometheus labels or Loki stream labels.

All errors, reconnects, failed runs, and operations above the configured slow
threshold are retained. The Collector tail-samples 10 percent of ordinary
successful control-plane traces. Because no frame/detection spans exist, the
Collector can receive unsampled control-plane records before making the tail
decision without unbounded volume.

Python logging uses structured records and injects active `trace_id` and
`span_id`. Native stderr is read by the supervisor, passed through
`redact_live_text`, assigned the current run context, and then emitted as a
Python structured log. Raw native stderr is never forwarded independently.

## Metrics

The existing Prometheus names in the livestream design remain required. Add:

```text
mvision_telemetry_queue_depth{signal}
mvision_telemetry_dropped_total{signal,reason}
mvision_telemetry_export_failures_total{signal}
mvision_native_operation_duration_seconds{operation,status}
mvision_live_trace_sampling_total{decision,reason}
```

Allowed labels are enum-only. `camera_id`, `run_id`, `track_id`, `face_id`,
name, URI, host, trace ID, and span ID are prohibited metric labels. Collector
internal telemetry is scraped so refused records, queue pressure, and exporter
failures are visible even when an application exporter is unhealthy.

## Privacy and Cardinality Gate

The following values are prohibited from all logs, span names, span attributes,
metric labels, exemplars, dashboard variables, and alert annotations:

- RTSP URI, host, userinfo, query, or credentials;
- person name, face ID, display label, or enrollment metadata;
- embedding/vector values or nearest-neighbor payloads;
- snapshot bytes, object-store credentials, or signed URLs;
- raw HTTP request/response bodies and native stack traces containing paths or
  secrets.

Collector filtering is defense in depth, not the primary redaction boundary.
Application tests must prove sanitized records before export. Loki uses only
low-cardinality resource labels such as `service_name` and environment. Trace
IDs remain structured metadata and query filters, never stream labels.

## Grafana Provisioning

Grafana data sources and dashboards are provisioned from version-controlled
files. Manual UI configuration is not an acceptance artifact.

Required data sources:

- Prometheus for application, native aggregate, span, and Collector metrics;
- Loki for OTLP logs;
- Tempo for traces and service graphs.

Tempo is provisioned with trace-to-logs and trace-to-metrics links. Loki exposes
derived links back to Tempo. Correlation uses service name plus trace ID filter,
without indexing trace ID as a Loki label.

Required dashboards:

1. `Mvision / Live Camera Operations`: state, frame age, source/processed/output
   FPS, reconnects, active tracks, output readiness, and stable errors.
2. `Mvision / Recognition Quality`: embedding coverage, quality rejects,
   Known/Unknown outcomes, score distributions, suppressions, and snapshot
   failures without identity dimensions.
3. `Mvision / Protocol and Backpressure`: queue depths, coalesces, drops, writer
   lag, malformed frames, stale revisions, and telemetry drops.
4. `Mvision / Dependencies`: PostgreSQL, Qdrant, object storage, Collector,
   Prometheus, Loki, and Tempo availability and latency.
5. `Mvision / Telemetry Health`: Collector refused/dropped/export-failed
   records, backend ingestion, sampling decisions, and storage growth.

## Alerts

The required self-hosted alert rules cover:

- live worker unavailable;
- ACTIVE camera frame age above threshold;
- reconnect storm;
- protocol or telemetry queue saturation/drops;
- embedding coverage regression;
- output frame stall;
- event or snapshot persistence failure;
- Collector/backend export failure;
- telemetry volume approaching its disk budget.

Alert delivery outside Grafana is not required. Rules and firing-state tests are
required; e-mail, Telegram, PagerDuty, and hosted channels remain non-goals.

## Storage and Retention

The first milestone uses dedicated local named volumes, isolated from Mvision
recognition data:

- Loki logs: 7 days, with Compactor retention enabled;
- Tempo traces: 7 days;
- Prometheus metrics: 15 days;
- Grafana database: persistent, with dashboards/data sources reproducible from
  checked-in provisioning.

No blanket object-store lifecycle rule is applied to Loki data. Existing
PostgreSQL, Qdrant, MinIO, model, and engine volumes are not mounted into the
telemetry backends. Multi-node/object-storage telemetry is a later deployment
decision.

## Failure and Backpressure Behavior

- Application OTLP export uses bounded batches, timeouts, and queues.
- Native operation events use the protocol's replace/coalesce policy and cannot
  consume reserved state/failure/stopped capacity.
- Telemetry queue full drops telemetry only and increments a low-cardinality
  counter.
- Collector and backend restarts do not restart the camera worker.
- Collector filtering rejects prohibited attributes and records a sanitized
  rejection count.
- Telemetry health affects the observability acceptance gate but not camera
  liveness/readiness unless the product itself is unhealthy.

## Acceptance Gates

1. A real camera trace joins API start, desired-state commit, supervisor claim,
   native STARTING/ACTIVE, evidence handling, Qdrant decision, snapshot action,
   event commit, and post-commit notification.
2. Grafana starts from empty telemetry volumes with all three provisioned data
   sources healthy and all five dashboards returning real data.
3. Trace-to-log, log-to-trace, trace-to-metrics, and service-graph navigation
   work from provisioned configuration.
4. Error, reconnect, slow, and ordinary-success sampling decisions match the
   configured policy.
5. Automated telemetry scans find no prohibited secret, URI, identity,
   embedding, snapshot, or high-cardinality label.
6. Collector, Loki, Tempo, and Prometheus fault injection leaves the camera
   pipeline ACTIVE or reconnecting for media reasons only; export recovers after
   backend restart and drops remain bounded/countable.
7. Enabled-versus-disabled observability A/B on the same fixture shows no more
   than 3 percent processed-FPS degradation and no telemetry-induced evidence
   or output drops.
8. Restart and time-controlled retention tests prove telemetry persistence and
   expiry without changing application data.

Mock spans or dashboard screenshots cannot promote these gates to PASS.

## Deployment and Security

The telemetry stack is an additive Compose profile with pinned immutable image
references and health checks. OTLP, Prometheus, Loki, and Tempo ports are
internal-only. Grafana is bound only to the configured trusted interface and
requires non-default credentials delivered through secrets, not committed
environment values. Production TLS/auth posture remains a release gate when
traffic leaves the trusted Docker network.

Every image, package, and dashboard plugin receives an exact version, source,
license, and vulnerability review before the deployment task receives PASS.
No unsigned third-party Grafana plugin is required.

## Source Basis

Official behavior reviewed for this design:

- OpenTelemetry Collector configuration and pipeline model:
  `https://opentelemetry.io/docs/collector/configuration/`
- OpenTelemetry Collector deployment rationale:
  `https://opentelemetry.io/docs/collector/`
- OTLP exporter endpoint/protocol configuration:
  `https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/`
- Grafana file provisioning:
  `https://grafana.com/docs/grafana/latest/administration/provisioning/`
- Tempo data-source provisioning and correlations:
  `https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/provision/`
- Loki native OTLP ingestion:
  `https://grafana.com/docs/loki/latest/send-data/otel/`
- Loki Compactor retention:
  `https://grafana.com/docs/loki/latest/operations/storage/retention/`
- Tempo Collector setup:
  `https://grafana.com/docs/tempo/latest/set-up-for-tracing/instrument-send/set-up-collector/otel-collector/`

Context7 was rechecked on 2026-07-22 against the stable OpenTelemetry Python
documentation for `TracerProvider`, `LoggerProvider`, batch span/log processors,
OTLP gRPC export, resources, and bounded shutdown. PyPI release indexes and
official project release pages must still be recorded with exact package/image
versions, licenses, and container digests before deployment artifacts are added.
