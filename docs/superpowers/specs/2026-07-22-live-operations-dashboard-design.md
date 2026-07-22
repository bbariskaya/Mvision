# Live Operations Dashboard Design

## Goal

Replace the metric-family showcase with one balanced operator dashboard that
answers whether the live pipeline is healthy, productive, and trustworthy.
Zero-valued anomaly counters remain visible as compact health indicators rather
than empty time-series panels.

## Primary View

The top row contains Worker Up, Runtime State, Current FPS, Face Load per 100 Frames, and
Embedding Coverage. The main trends show decoded FPS, tracked/eligible face
throughput, embedding throughput, missing-embedding ratio, faces per frame, and
native/dependency p95 latency.

Reconnects, protocol drops, and telemetry export failures are compact stat
panels. Zero is green and a positive recent value is warning or critical. Event
and output metrics are removed from the primary view until their producers are
implemented and verified.

## Metrics

Native cumulative counters are converted to process-local Prometheus deltas:

- decoded frames;
- tracked objects;
- eligible objects;
- embeddings;
- missing embeddings;
- cosine samples;
- dropped evidence.

Derived PromQL values include embedding coverage, eligibility ratio,
missing-embedding ratio, faces per frame, and current FPS. Application IDs,
person data, URIs, hosts, trace IDs, and span IDs are never metric labels or
dashboard variables.

## Errors And Correlation

Recent Error Traces uses Tempo TraceQL with service scope and `status = error`.
Correlated Live Logs uses Loki service labels and structured trace metadata.
Provisioned links support Loki log to Tempo trace and Tempo trace to Loki logs.
Only stable `error_code` values are displayed; raw exception messages and native
stderr are not exported.

## Verification

An acceptance smoke command emits an `OBSERVABILITY_SMOKE_TEST` error span and a
correlated safe log without interrupting media processing. Acceptance requires
the same trace ID in Tempo and Loki, working bidirectional links, live FPS and
embedding metrics changing over time, bounded series cardinality, and zero
prohibited plaintext. The smoke error is visibly distinguishable from product
errors.

## Scope

This change does not add per-frame spans, camera-ID metric labels, new media
behavior, or GPU/host exporters. GPU, CPU, and RSS dashboards remain a later
extension rather than delaying completion of the observability phase.
