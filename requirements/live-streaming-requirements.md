# Face Recognition API - Live Streaming Requirements

## 1. Product Outcome

This document extends `requirements/videorequirements.md` to continuous live
sources. Existing image and video identity semantics remain valid where they
apply to an unbounded stream.

The default live result is JSON for every processed frame. It contains the
frame time and dimensions plus every detected face's bounding box, landmarks,
tracker state, identity state, and confidence values. A processed frame with no
face still produces a successful result with an empty `faces` array.

Person-based `firstSeen`, `lastSeen`, intervals, and total duration are an
optional aggregation output. Recording and annotated media are also optional.

## 2. Canonical Media Ingress

Mvision MediaMTX is the media boundary between a caller-owned source and the GPU
worker. A session supports these typed source variants:

- `rtspPull`: Mvision pulls an RTSP URL;
- `whepPull`: Mvision pulls a WebRTC/WHEP URL;
- `whipPush`: the caller publishes to a Mvision-generated WHIP URL.

For every variant, MediaMTX exposes one generation-scoped internal RTSP path to
the DeepStream worker. DeepStream does not implement separate caller-facing
WebRTC ingest logic.

For `whipPush`, session creation returns a write-only publish URL and the session
waits for media automatically. For pull modes, source credentials are encrypted
before persistence and never returned by the API.

MediaMTX Control API configuration is runtime state, not durable configuration.
PostgreSQL stores desired session state and a reconciler recreates required
paths after MediaMTX or controller restart.

## 3. Session Lifecycle

- `POST /api/v1/live/sessions` validates, persists, provisions, and immediately
  begins starting the session.
- A push session may remain `WAITING_FOR_SOURCE` until its publisher connects.
- Runtime states are `ACCEPTED`, `WAITING_FOR_SOURCE`, `STARTING`, `ACTIVE`,
  `RECONNECTING`, `STOPPING`, `STOPPED`, and `FAILED`.
- Every session has an immutable current generation and a requested/resolved
  configuration snapshot.
- Reconfiguration creates the next generation and performs a controlled restart.
- Results and media paths are fenced by session ID and generation.
- A caller may provide a camera identifier and optional location object. The
  generation stores a snapshot; later edits do not rewrite historical results.
- API authentication uses the deployment's configured API key.

## 4. Typed Processing Configuration

The caller selects a built-in, versioned profile and may provide supported typed
overrides. The initial API does not include profile publication or arbitrary
pipeline graph management.

Supported controls include:

- analytics mode: `detect`, `detectTrack`, or `recognize`;
- processed-frame sampling rate;
- detector, recognition, anonymous-match, and ambiguity thresholds;
- tracking maximum gap and recognition evidence count;
- optional persistent anonymous identity creation;
- source latency, timeout, and reconnect policy;
- frame JSON connector references and retention policy;
- optional appearance aggregation;
- optional recording and annotated output settings.

Recognition always uses the model-compatible five-point alignment path. Callers
cannot provide model paths, TensorRT engines, filesystem configuration paths,
GStreamer properties, shell commands, GPU IDs, ports, or MediaMTX API payloads.
Unknown or contradictory fields are validation errors and are never ignored.

## 5. Default Frame JSON

The system emits one `frame.result` object for every frame selected by the
session's sampling policy. Frame sequence is monotonic within one generation.

```json
{
  "eventId": "uuid-v7",
  "eventType": "frame.result",
  "schemaVersion": 1,
  "sessionId": "uuid",
  "generation": 2,
  "cameraId": "gate-1",
  "location": {
    "site": "office-a",
    "area": "entrance",
    "displayName": "Office A Entrance"
  },
  "frame": {
    "sequence": 1842,
    "observedAt": "2026-07-23T10:15:12.420Z",
    "ptsNs": 61400000000,
    "timeBasis": "mvisionObservedUtc",
    "width": 1920,
    "height": 1080
  },
  "faces": [
    {
      "detectionId": "uuid-v7",
      "trackId": "42",
      "faceId": "uuid-or-null-while-pending",
      "status": "known",
      "name": "Baris",
      "metadata": {},
      "boundingBox": {"x": 640, "y": 220, "width": 180, "height": 180},
      "landmarks": [
        {"x": 684, "y": 270},
        {"x": 748, "y": 271},
        {"x": 717, "y": 306},
        {"x": 691, "y": 344},
        {"x": 744, "y": 344}
      ],
      "detectorConfidence": 0.93,
      "recognitionConfidence": 0.94
    }
  ]
}
```

Rules:

- Geometry uses original source-frame pixels, even when inference is downscaled.
- `trackId` is local to one session generation and is not a global identity.
- `faceId` may be null while identity is pending; once a known or persistent
  anonymous identity is confirmed, subsequent frame results carry its global ID.
- Valid statuses are `pending`, `known`, `anonymous`, `newAnonymous`, and
  `unknown` as applicable to the selected identity mode.
- Embeddings, aligned crops, source credentials, and internal media paths never
  appear in frame JSON.
- Sampling controls how many frames are processed; every processed frame produces
  exactly one frame result.

## 6. Optional Appearance Aggregation

When `appearanceSummary.enabled=true`, Mvision additionally produces
`appearance.started` and `appearance.ended` events and durable pull results.
These events do not replace frame results.

An appearance result contains:

- global `faceId`, identity status snapshot, permitted name, and metadata;
- camera ID and optional location snapshot;
- first and last observed UTC;
- one or more raw intervals;
- total observed duration as the sum of interval durations;
- session ID, generation, local track references, and final confidence.

Tracker expiry, confirmed identity switch, session stop, or an untrusted timing
reset closes an interval. Short misses within the configured tracker gap do not.
Time between separate intervals is never counted as observed duration.

## 7. Identity Semantics

- Known identities retain their global persistent `faceId`.
- Persistent anonymous identity mode searches existing anonymous identities and
  reuses their `faceId` when accepted.
- A new anonymous identity is created only after sufficient quality-gated,
  temporally separated evidence and a final duplicate check.
- The first accepted occurrence uses `newAnonymous`; later occurrences use
  `anonymous`.
- Enrollment changes an anonymous identity to known without changing `faceId`.
- Detection-only modes do not fabricate identity values.

## 8. Time Semantics

Stream PTS and absolute UTC are separate values. PTS must never be interpreted as
Unix epoch time.

The initial live contract uses `mvisionObservedUtc`: a stable wall-clock anchor
plus monotonic stream progression for one timing epoch. If trusted source UTC is
available later, it may be exposed under a distinct `timeBasis`. Reconnects or
timestamp discontinuities start a new timing epoch rather than silently joining
uncertain time ranges.

Exact recording-sample indexes and zero-frame recording joins are not required
by the initial live release.

## 9. JSON Access And Delivery

- Registered Webhook and Kafka connectors are selected with `connectorRef`.
- Normal session requests do not contain raw destinations or credentials.
- Frame JSON is dispatched through a direct asynchronous path; connector I/O
  never runs on a GStreamer streaming thread and never blocks inference.
- PostgreSQL persistence and connector delivery consume separate queues.
- Stable event IDs allow consumers to deduplicate retries.
- The direct Webhook path does not claim crash-safe at-least-once delivery.
- Kafka durability begins after broker acknowledgement according to connector
  configuration.
- Pull APIs provide persisted recovery and history; newly delivered direct events
  may briefly precede their pull-API visibility.
- Each connector has bounded capacity. Saturation is observable. Frame events may
  be rejected or dropped according to the declared connector policy rather than
  stalling inference; the API validates obviously unsustainable requested rates.

## 10. Optional Recording

- Recording is disabled unless requested.
- MediaMTX records the canonical, unannotated ingress stream as fMP4.
- Production segment duration defaults to 15 minutes and is typed/configurable.
- Completed segments are retained on persistent storage and may be uploaded to
  the existing MinIO service asynchronously.
- PostgreSQL stores segment state, actual start/end time, duration, path/object
  reference, checksum, session, generation, camera, and location snapshot.
- Recording failure is reported independently and does not stop frame JSON or
  recognition.
- The initial release does not require a per-sample sidecar or exact-frame
  evidence resolver.

## 11. Optional Annotated Output

- Annotated output is disabled unless requested.
- A JSON-only session creates no OSD, encoder, publisher, or annotated path.
- Typed controls cover boxes, landmarks, labels, colors, and line width.
- The worker publishes to a generation-scoped MediaMTX path.
- The API returns simple RTSP and WebRTC viewer URLs only after that path is ready.
- Viewer authentication is not required for the target deployment.
- Viewer or publisher backpressure must not block inference, frame JSON, or
  recording.

## 12. Multi-Camera Execution

- Initial multi-camera execution uses one isolated native process per active
  session.
- Existing PostgreSQL claim and lease fencing assigns work across a fixed worker
  pool.
- The single-running-camera database constraint and fixed per-worker public media
  port are removed.
- One source, process, connector, recording, or viewer failure cannot mutate
  another session.
- Shared dynamic DeepStream batching is a later measured optimization.
- Cross-camera body ReID and trajectory stitching are out of scope.

## 13. API Surface

```text
GET  /api/v1/live/capabilities
POST /api/v1/live/connectors
POST /api/v1/live/sessions
GET  /api/v1/live/sessions
GET  /api/v1/live/sessions/{sessionId}
POST /api/v1/live/sessions/{sessionId}/reconfigure
POST /api/v1/live/sessions/{sessionId}/stop
GET  /api/v1/live/sessions/{sessionId}/frames
GET  /api/v1/live/sessions/{sessionId}/appearances
GET  /api/v1/live/sessions/{sessionId}/recordings
GET  /api/v1/live/faces/{faceId}/appearances
```

Every endpoint has an OpenAPI request, response, and stable error contract.

## 14. Failure Behavior

- Invalid session combinations fail before source connection.
- Source, worker, JSON connector, persistence, recording, and annotated output
  states fail independently.
- A source reconnect never reports false `ACTIVE` while frames are stale.
- A worker restart closes uncertain track intervals and never invents duration.
- No-face frames are successful empty results.
- MediaMTX path reconciliation is idempotent after restart.
- Secrets and embeddings do not enter responses, events, logs, traces, or metrics.

## 15. Acceptance

Acceptance includes:

- RTSP pull, WHEP pull, and WHIP push contract tests using MediaMTX fixtures;
- one frame JSON for every processed frame, including empty-face frames;
- original-pixel bbox and landmark parity against deterministic fixtures;
- stable track IDs and correct known/persistent-anonymous transitions;
- optional appearance first/last/interval/duration correctness;
- direct connector outage without inference interruption and visible drops/retries;
- JSON-only execution with no encoder or annotated MediaMTX path;
- optional annotated RTSP and WebRTC playback with a stalled-viewer test;
- fast short-segment recording tests plus one real 15-minute rollover;
- MediaMTX restart followed by desired-path reconciliation;
- controlled generation reconfiguration and stale-result fencing;
- simultaneous isolated camera sessions before multi-camera PASS;
- explicit PASS, PARTIAL, BLOCKED, and NOT_TESTED runtime evidence.
