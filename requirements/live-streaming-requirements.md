# Face Recognition API - Live Streaming Additional Requirements

## 1. Purpose And Relationship To Existing Requirements

This document extends `requirements/videorequirements.md` to continuous live
sources. Existing image and video identity semantics remain valid unless this
document explicitly narrows them for an unbounded stream.

The primary live product result is not an annotated video. It answers:

- which global person identity appeared;
- at which caller-provided camera/location;
- during which absolute UTC intervals;
- for how much total observed duration;
- and which retained recording samples provide evidence for the result.

Annotated streaming, recording, per-frame detections, and external event
delivery are configurable outputs. They do not replace the appearance result.

## 2. Caller-Owned Source And Location

- A caller may register a durable camera source or start an authorized session
  with an inline source.
- RTSP credentials are write-only and must be encrypted before persistence.
- Mvision must never infer a physical location from camera pixels.
- A caller may register a typed location and associate it with a camera source.
- A location contains a caller-scoped identifier, site identifier, area or zone
  identifier, and display name.
- Location association is optional. When absent, results contain the camera ID
  and `location: null`.
- A session snapshots its location at generation start. Later source/location
  edits must not rewrite historical appearances.

## 3. Session-Based Processing

- Every live run belongs to a durable session and immutable generation.
- The caller selects a versioned pipeline profile and typed request overrides.
- Changing processing behavior creates a new generation and a controlled
  restart; an active generation is never mutated silently.
- A session exposes explicit desired and runtime state.
- Source start, stop, reconfigure, worker assignment, reconnect, and failure are
  fenced by session ID and generation.
- A request idempotency key must not create duplicate sessions.
- Existing global environment values may seed platform defaults but are not the
  runtime source of truth after session compilation.

## 4. Typed Pipeline Configuration

The API must expose typed, versioned configuration for at least:

- analytics mode: detection, detection with tracking, or recognition;
- sampling mode and rate;
- detector, recognition, quality, and ambiguity thresholds;
- alignment mode;
- tracker policy and maximum observation gap;
- global anonymous identity behavior;
- appearance interval and merge-gap behavior;
- source latency, timeout, and reconnect policy;
- recording enablement, segment duration, and retention;
- JSON result granularity and connector references;
- annotated stream enablement, protocols, bounding-box style, landmark style,
  and label fields;
- resource class and admin-scoped placement constraints.

Callers must not supply filesystem config paths, arbitrary GStreamer properties,
model binaries, shell commands, raw GPU process arguments, or MediaMTX control
API payloads.

Recognition requires the model-compatible alignment mode. Contradictory fields
must produce a stable validation error instead of being ignored.

## 5. Identity Semantics

- Known, anonymous, and new-anonymous retain their existing global meaning.
- Known and active anonymous identities use global persistent `faceId` values.
- A raw tracker ID is local to one camera session generation and must never be
  used as a global identity.
- A new anonymous identity may be created only after bounded quality-gated,
  temporally diverse evidence and a final gallery recheck.
- Every raw tracker must not automatically create an anonymous identity.
- Storage failures must not leave a half-active anonymous identity.
- Later recognition of the same anonymous person reuses the same `faceId`.
- Enrollment changes lifecycle state to known without changing `faceId`.
- Concurrent sessions must use fencing and final duplicate checks before
  creating a new global anonymous identity.

## 6. Appearance Results

The primary result is grouped by global person identity, camera, and caller
location. Each result contains at least:

- `faceId`;
- identity status snapshot;
- known name and permitted metadata when applicable;
- camera ID;
- optional caller-provided location snapshot;
- first seen UTC;
- last seen UTC;
- total observed duration;
- raw appearance intervals;
- session ID, generation, and timing epoch;
- recording evidence state and references.

Rules:

- Total duration is the sum of raw interval durations. Time between separate
  intervals must not be counted.
- A short detector miss that remains within the same valid tracker lifecycle
  does not split an interval.
- Tracker expiry, confirmed identity switch, session stop, or untrusted timing
  discontinuity closes the raw interval.
- A recording segment boundary does not close an appearance interval.
- Query presentation may merge adjacent intervals for the same face and location
  within a configured merge gap, but immutable raw intervals remain available.
- If identity confirmation arrives late, the interval may start at the earliest
  quality-gated and trusted observation retained by that track.
- No-face periods are successful empty observation periods, not failures.

## 7. Time Contract

Every retained observation includes:

- source absolute UTC when available;
- source media time represented without floating-point loss;
- same-timestamp access-unit ordinal when needed;
- stream PTS in nanoseconds for diagnostics;
- receive UTC for latency diagnostics;
- time basis and time-quality enum;
- timing epoch.

MediaMTX absolute timestamps derived from RTCP sender reports are preferred.
Receive time must never be silently substituted for trusted source UTC.

Reconnect, timestamp jump, or unproven timestamp continuity creates a new timing
epoch. Intervals on opposite sides of an untrusted epoch boundary are not merged
as one raw interval.

## 8. Recording And Evidence

- Recording is optional per session.
- When enabled, Mvision MediaMTX records fMP4 segments using the same ingress
  time basis consumed by inference.
- Production segment duration defaults to 15 minutes and is typed/configurable.
- Completed segments are delivered to Mvision ingestion, uploaded to MinIO, and
  represented by PostgreSQL manifests.
- The full exact sample index is an immutable MinIO sidecar; PostgreSQL stores
  business metadata and resolved evidence pointers.
- A segment is `READY` only after video, index, checksums, and manifest finalize.
- Recording evidence states are `pending`, `exact`, or `unaligned` with a stable
  reason.
- Exact evidence maps an observation to one recording segment and one exact video
  sample index.
- Nearest-frame, nominal-FPS, file-time, or receive-time fallback is forbidden.
- Recording failure does not erase a realtime appearance, but the evidence gap
  remains visible and auditable.

## 9. Result Access And Delivery

- Durable pull APIs are always available for session, appearance, detection,
  recording, and face-history results.
- Registered webhook and Kafka connectors are supported.
- Callers select connectors by `connectorRef`; raw destinations and credentials
  are not accepted in normal session requests.
- PostgreSQL result/outbox rows are authoritative for external delivery.
- Delivery is at-least-once with a stable event ID for consumer deduplication.
- Ordering is preserved per session generation.
- Retry, terminal failure, replay, and dead-letter state are queryable.
- Per-frame detection delivery is optional and independently retained; it must
  not inflate the primary appearance response by default.

## 10. Optional Annotated Streaming

- Annotated output is disabled unless requested by the session specification.
- A JSON-only session must not create an encoder, RTP output, MediaMTX annotated
  path, or viewer URL.
- When requested, the system creates the configured OSD and media branch and
  returns URLs only after the path is actually ready.
- Bounding-box enablement, color, line width, landmark rendering, and label
  fields are typed request fields.
- OSD behavior does not alter recognition, appearance, recording, or result
  delivery semantics.
- A stalled viewer must not block decode, inference, result persistence, or
  recording.

## 11. Multi-Camera Extensibility

- The first configurable session implementation may retain one active pipeline
  per worker, but all contracts must be camera/session scoped.
- Workers advertise capabilities and resource availability.
- A scheduler owns GPU placement, leases, admission control, and recovery.
- Normal callers choose resource classes, not arbitrary GPU process arguments.
- One camera failure must not mutate another camera's state or outputs.
- Dynamic batching is a measured later optimization, not a prerequisite for
  correctness-oriented multi-camera scheduling.

## 12. Security And Privacy

- Source and connector credentials never appear in API responses, logs, traces,
  metrics, events, manifests, or process arguments.
- Connector destinations are registered, validated, caller-scoped resources.
- Webhook destinations must be allowlisted against SSRF policy.
- Kafka TLS/SASL material is stored as encrypted secret data or secret
  references, never in session specs returned to callers.
- Embeddings never appear in result delivery, manifests, metrics, or annotated
  output metadata.
- Dynamic IDs, names, locations, timestamps, paths, and trace IDs are not
  Prometheus labels.
- Every state-changing API operation is authenticated, authorized, and audited.

## 13. Failure Behavior

- Capacity exhaustion returns a stable rejection; it never produces false
  `ACTIVE` state.
- Invalid field combinations fail before source connection.
- Source, worker, recording, connector, and storage states fail independently.
- Result persistence is authoritative and must not depend on external connector
  availability.
- Connector failure never stops media processing.
- Recording failure never fabricates exact evidence.
- Timing degradation never fabricates source UTC.
- Worker restart never silently extends an uncertain appearance duration.
- Partial uploads and orphan objects are reconciled without destructive volume
  reset.

## 14. Acceptance Requirements

Acceptance includes:

- contract tests for every supported and forbidden session option combination;
- deterministic known and global-anonymous appearance timelines;
- correct first seen, last seen, interval, and total duration behavior;
- exact zero-frame recording evidence on fast 15-second segments;
- at least one real 15-minute segment rollover and durable ingestion;
- inference restart without stopping recording;
- upstream reconnect and timing-epoch fencing;
- JSON-only execution with no annotated media branch;
- requested annotated stream with a ready URL and non-blocking viewer behavior;
- webhook and Kafka at-least-once delivery with duplicate-safe event IDs;
- connector outage with uninterrupted live analytics;
- controlled reconfiguration into a new immutable generation;
- multi-camera admission, isolation, and recovery tests before multi-camera PASS;
- explicit PASS, PARTIAL, BLOCKED, and NOT_TESTED reporting for every real-runtime
  gate.
