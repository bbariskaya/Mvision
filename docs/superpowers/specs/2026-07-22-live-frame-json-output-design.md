# Live Frame JSON Output Design

**Status:** Approved direction
**Delivery:** 2 - Frame JSON And Optional Appearance
**Revised:** 2026-07-23

## Goal

Generate one JSON result for every frame selected by the session sampling policy.
The default result is frame-oriented and contains bbox, landmarks, tracker and
identity state, and confidence. Person appearance summaries are an additional
optional projection, not the default payload.

## Internal And External Events

The native pipeline has two distinct event classes:

- internal identity evidence: quality-ranked embeddings and aligned crops used
  only for identity resolution;
- external frame results: safe geometry and identity snapshots with no embedding
  or image bytes.

These events must not share one overloaded schema. Internal evidence may be
coalesced per track and carries restricted data. External frame results follow
the public JSON contract.

## Native Frame Result

Add a versioned `frame_result` native message containing:

- protocol header with session ID, run ID, and generation;
- monotonic frame sequence within the generation;
- stream PTS in nanoseconds when valid;
- Mvision observed UTC in integer nanoseconds;
- source-frame width and height;
- zero or more face observations.

Each face observation contains:

- detection ordinal;
- local tracker ID when tracking is enabled;
- current identity epoch and state;
- global face ID, display name, and recognition score when confirmed;
- original-pixel bbox;
- five original-pixel landmarks and landmark confidence;
- detector confidence;
- safe quality summary.

Embedding vectors and aligned JPEG bytes remain confined to
`track_evidence` messages.

## Frame Selection

`processing.sampling` defines which input frames are processed and emitted.

Supported initial modes:

```text
everyNFrames(value >= 1)
targetFps(value > 0)
```

The native pipeline assigns a monotonically increasing input sequence and an
emitted-frame sequence. A selected frame produces exactly one `frame_result`,
even if the face list is empty. A sequence gap at an external connector means
delivery loss/backpressure, not an undetected no-face frame.

## Time Contract

The current `frame->buf_pts` value is stream-relative and must not be converted
directly with `datetime.fromtimestamp()`.

The public frame object carries:

```text
observedAtUnixNs   # wall-clock time at Mvision observation
ptsNs              # stream presentation time, diagnostic/order only
timeBasis          # mvisionObservedUtc in v1
timingEpoch        # increments across untrusted discontinuity
```

UTC is serialized as RFC 3339 with sufficient precision. Integer nanoseconds are
retained internally; floating-point seconds are not used as persistence keys.

Trusted source UTC may be introduced later under a different `timeBasis`. It
must never silently replace or be confused with observed UTC.

## Public Frame Envelope

```json
{
  "eventId": "019f...",
  "eventType": "frame.result",
  "schemaVersion": 1,
  "occurredAt": "2026-07-23T10:15:12.420Z",
  "sessionId": "019f...",
  "generation": 2,
  "cameraId": "gate-1",
  "location": {
    "site": "office-a",
    "area": "entrance",
    "displayName": "Office A Entrance"
  },
  "frame": {
    "sequence": 1842,
    "ptsNs": 61400000000,
    "timeBasis": "mvisionObservedUtc",
    "timingEpoch": 1,
    "width": 1920,
    "height": 1080
  },
  "faces": [
    {
      "detectionId": "019f...",
      "trackId": "42",
      "identityEpoch": 1,
      "faceId": "019f...",
      "status": "known",
      "name": "Baris",
      "metadata": {},
      "boundingBox": {"x": 640, "y": 220, "width": 180, "height": 180},
      "landmarks": [
        {"x": 684, "y": 270, "confidence": 0.98},
        {"x": 748, "y": 271, "confidence": 0.98},
        {"x": 717, "y": 306, "confidence": 0.97},
        {"x": 691, "y": 344, "confidence": 0.96},
        {"x": 744, "y": 344, "confidence": 0.96}
      ],
      "detectorConfidence": 0.93,
      "recognitionConfidence": 0.94,
      "quality": {"acceptedForIdentity": true}
    }
  ]
}
```

## Identity State In Frame Results

Identity resolution is asynchronous relative to frame processing. The result is
therefore an honest snapshot at emission time:

- `pending`: tracking exists but identity evidence is not yet sufficient;
- `known`: a named global identity is accepted;
- `anonymous`: an existing persistent anonymous identity is accepted;
- `newAnonymous`: a new persistent anonymous identity became active;
- `unknown`: identity mode is disabled or no persistent identity is assigned.

`faceId` is null for `pending` and non-persistent `unknown`. It is required for
`known`, `anonymous`, and `newAnonymous`.

An identity assignment applies only when its session, run, generation, tracker,
identity epoch, decision sequence, and revision are current. Late assignments
cannot rewrite already delivered frame events. Persisted query projections may
optionally expose a separate later-resolved identity relation without mutating
the original event payload.

## Persistent Anonymous Identity

The live path extends existing identity storage instead of generating temporary
native IDs.

Creation requires:

- minimum quality-accepted evidence count;
- temporal separation and minimum dwell;
- no accepted known or anonymous gallery match;
- final gallery recheck before creation;
- PostgreSQL identity/sample creation;
- MinIO evidence upload and Qdrant vector activation;
- activation only after required storage operations succeed.

The first confirmed frame uses `newAnonymous`. Subsequent frames and sessions use
`anonymous` with the same `faceId`. Enrollment changes lifecycle state to known
without changing that ID.

## Track Lifecycle

Native tracking must emit `track_expired`; defining the protocol type alone is
insufficient.

Track state records last observed media time and monotonic receive time. A track
expires when:

- absent beyond configured `trackGapMs`;
- tracker explicitly removes it;
- confirmed identity epoch changes;
- source timing epoch changes;
- session stops or the graph is rebuilt.

Expiry is a critical control event. It must not be silently dropped by the same
best-effort queue used for high-volume frame output.

## Optional Appearance Projection

When enabled, an aggregator consumes track and identity lifecycle events and
creates person-oriented output.

```json
{
  "eventId": "019f...",
  "eventType": "appearance.ended",
  "schemaVersion": 1,
  "sessionId": "019f...",
  "generation": 2,
  "cameraId": "gate-1",
  "location": {
    "site": "office-a",
    "area": "entrance"
  },
  "person": {
    "faceId": "019f...",
    "status": "known",
    "name": "Baris",
    "metadata": {}
  },
  "firstSeen": "2026-07-23T10:15:12.420Z",
  "lastSeen": "2026-07-23T10:15:24.980Z",
  "totalDurationSeconds": 12.56,
  "intervals": [
    {
      "start": "2026-07-23T10:15:12.420Z",
      "end": "2026-07-23T10:15:24.980Z",
      "durationSeconds": 12.56
    }
  ],
  "confidence": 0.94
}
```

Appearance output requires a global `faceId`. Pending and non-persistent unknown
tracks remain visible in frame JSON but do not fabricate person summaries.

`appearance.started` is emitted when a global identity is accepted and may
backdate to the earliest retained quality observation. `appearance.ended`
contains the finalized interval. Total duration sums intervals and excludes
absence gaps.

## Connector Model

Connectors are registered resources. Initial types:

- Webhook with URL, auth secret, timeout, and bounded retry configuration;
- Kafka with brokers, topic, TLS/SASL secret, acknowledgement, and timeout
  configuration.

The session selects connector IDs and event allowlists. Raw destinations and
credentials are not accepted in the session request.

Frame delivery path:

```text
native frame callback
  -> bounded safe-envelope queue
       -> connector-specific queue
            -> Webhook or Kafka client

native frame callback
  -> independent optional persistence queue
       -> batch PostgreSQL writer
```

No connector or PostgreSQL network call occurs in the native callback or
GStreamer probe.

## Delivery Guarantees

- Event IDs are stable and consumers deduplicate by event ID.
- Ordering is represented by session, generation, and frame sequence.
- Direct Webhook delivery is low latency but not crash-safe at-least-once.
- In-process retry may duplicate a Webhook event.
- Kafka durability starts when the configured broker acknowledgement succeeds.
- Connector outage never stops the media pipeline.
- Frame queues are bounded. Under saturation, frame events may drop according to
  connector policy and sequence gaps/drop counters make loss visible.
- Critical track-expiry and session-state events use a separate non-frame control
  path and are not sacrificed to preserve frame throughput.
- Crash-safe delivery replay and a PostgreSQL outbox are deferred without
  changing the public event envelope.

## Persistence And Pull APIs

Frame persistence is optional because continuous frame JSON is high volume. A
session must configure at least one JSON sink: a connector or frame persistence.

When enabled, frame rows are batch-written with bounded retention. The storage
shape keeps common query fields typed and the safe face list as versioned JSON.
It does not store embeddings.

Appearance rows are durable whenever appearance summary is enabled.

```text
GET /api/v1/live/sessions/{sessionId}/frames
GET /api/v1/live/sessions/{sessionId}/appearances
GET /api/v1/live/faces/{faceId}/appearances
```

Queries use cursor pagination, generation filters, UTC half-open ranges, and
bounded page sizes. Frame and appearance results are separate; one is never
silently expanded into the other.

## Backpressure Admission

The API estimates the requested frame event rate from sampling and connector
count. It rejects a configuration beyond declared deployment limits before
starting GPU work.

Runtime metrics include:

- generated frame results;
- delivered, retried, failed, and dropped results by connector type;
- current queue depth and high-watermark events;
- persistence batch latency/failure;
- frame-sequence gaps observed by test consumers;
- track evidence coalescing and critical control-event failures.

Dynamic session IDs, face IDs, event IDs, URLs, and person names are not metric
labels.

## Stable Errors

- `LIVE_JSON_SINK_REQUIRED`;
- `LIVE_FRAME_RATE_UNSUPPORTED`;
- `LIVE_CONNECTOR_NOT_FOUND`;
- `LIVE_CONNECTOR_TYPE_UNSUPPORTED`;
- `LIVE_CONNECTOR_CAPACITY_EXCEEDED`;
- `LIVE_FRAME_PERSISTENCE_FAILED`;
- `LIVE_IDENTITY_PERSISTENCE_FAILED`;
- `LIVE_APPEARANCE_STATE_INVALID`.

## Acceptance

- every selected fixture frame creates one frame envelope;
- no-face frames contain `faces: []` and are not failures;
- sequence, PTS, observed UTC, timing epoch, and dimensions are correct;
- bbox and landmarks match original-pixel fixture coordinates;
- detection, tracking, and recognition modes expose only valid fields;
- pending-to-known and pending-to-new-anonymous transitions are deterministic;
- later anonymous appearances reuse the same global `faceId`;
- native track expiry closes optional appearances at the correct time;
- appearance total duration excludes gaps;
- embeddings and aligned crops never enter public JSON or frame persistence;
- slow Webhook and unavailable Kafka fixtures do not stop frame processing;
- forced queue saturation produces visible sequence gaps and bounded memory;
- critical expiry survives frame-queue saturation;
- persisted frame and appearance cursor queries return correct generation-scoped
  results;
- direct Webhook semantics are documented and never presented as crash-safe
  at-least-once.
