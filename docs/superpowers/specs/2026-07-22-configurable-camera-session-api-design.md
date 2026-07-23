# Configurable Live Session API Design

**Status:** Approved direction
**Delivery:** 1 - Session API And Media Ingress
**Revised:** 2026-07-23

## Goal

Replace fixed camera registration, body-less start, global runtime settings, and
fixed output ports with one typed live-session contract. Session creation starts
work immediately and supports customer MediaMTX streams without adding WebRTC
logic to the DeepStream worker.

## Non-Goals

- profile publication or arbitrary user-created model stacks;
- raw GStreamer, DeepStream, TensorRT, GPU, port, or filesystem settings;
- arbitrary MediaMTX Control API payloads;
- hot mutation of an active graph;
- multi-camera placement policy beyond the existing worker claim/lease boundary;
- OIDC, RBAC, and multi-tenant administration in the initial deployment.

## API Surface

```text
GET  /api/v1/live/capabilities

POST /api/v1/live/connectors
GET  /api/v1/live/connectors
GET  /api/v1/live/connectors/{connectorId}
DELETE /api/v1/live/connectors/{connectorId}

POST /api/v1/live/sessions
GET  /api/v1/live/sessions
GET  /api/v1/live/sessions/{sessionId}
POST /api/v1/live/sessions/{sessionId}/reconfigure
POST /api/v1/live/sessions/{sessionId}/stop
```

All routes require the configured API key. Connector secrets and source URLs are
write-only.

## Source Contract

Exactly one source variant is required.

### RTSP Pull

```json
{
  "source": {
    "type": "rtspPull",
    "url": "rtsp://customer-mediamtx:8554/camera-1"
  }
}
```

### WHEP Pull

```json
{
  "source": {
    "type": "whepPull",
    "url": "wheps://customer-mediamtx.example/camera-1"
  }
}
```

### WHIP Push

```json
{
  "source": {
    "type": "whipPush"
  }
}
```

For pull sources, Mvision configures a generation-scoped MediaMTX path whose
`source` is the supplied RTSP or WHEP URL. For push sources, the path uses
`source: publisher` and the response includes a WHIP endpoint.

All variants become this worker input:

```text
rtsp://mediamtx:8554/ingress/{opaqueGenerationPath}
```

The internal URL is never accepted from or returned to the caller.

## Session Request

```json
{
  "schemaVersion": 1,
  "cameraId": "gate-1",
  "location": {
    "site": "office-a",
    "area": "entrance",
    "displayName": "Office A Entrance"
  },
  "profile": "face-recognition-v1",
  "source": {
    "type": "whipPush"
  },
  "processing": {
    "mode": "recognize",
    "sampling": {"mode": "everyNFrames", "value": 1},
    "detectorThreshold": 0.5,
    "recognitionThreshold": 0.62,
    "anonymousThreshold": 0.7,
    "top2Margin": 0.05,
    "minimumIdentityEvidence": 3,
    "trackGapMs": 1500,
    "persistentAnonymous": true
  },
  "sourcePolicy": {
    "latencyMs": 100,
    "frameTimeoutMs": 5000,
    "reconnectIntervalMs": 2000,
    "reconnectAttempts": -1
  },
  "json": {
    "connectorRefs": ["connector-uuid"],
    "persistFrames": true,
    "frameRetention": "24h",
    "appearanceSummary": {"enabled": false}
  },
  "recording": {
    "enabled": true,
    "segmentDuration": "15m",
    "retention": "7d"
  },
  "annotatedStream": {
    "enabled": true,
    "boundingBox": {"enabled": true, "lineWidth": 3},
    "landmarks": {"enabled": true},
    "labelFields": ["name", "status", "recognitionConfidence"]
  }
}
```

`location` is an inline caller-owned snapshot rather than a separate first-release
resource. It is optional and does not attempt to infer physical location.

## Profiles And Overrides

The initial service owns a small set of immutable built-in profiles. A profile
contains approved model and tracker artifacts plus safe defaults. The request may
override only fields declared by capabilities.

```text
built-in profile version
  + validated typed overrides
  = immutable resolved generation configuration
```

The generated native command contains resolved internal values. The caller never
selects model files, GPU IDs, sockets, MediaMTX paths, or output ports.

### Processing Dependencies

- `detect` produces boxes, landmarks, and detector confidence;
- `detectTrack` additionally produces local tracker IDs;
- `recognize` requires tracking, quality evidence, five-point alignment, ArcFace,
  and identity resolution;
- persistent anonymous identity requires `recognize`;
- appearance summary requires tracking and a configured track gap;
- identity labels/colors require `recognize`;
- disabling recording and annotated output creates neither media branch;
- every selected processing mode still emits one frame JSON per processed frame.

Recognition alignment is not caller-selectable in v1. This removes the invalid
`recognize + alignment:none` state rather than exposing a switch that has only one
correct value.

## Capabilities

`GET /api/v1/live/capabilities` returns a small cacheable document containing:

- session schema versions;
- available built-in profiles and exact profile versions;
- source types;
- processing and sampling modes;
- allowed override fields, bounds, and defaults;
- connector types;
- recording duration/retention bounds;
- annotated OSD fields and viewer protocols;
- current maximum concurrent session count.

It is discovery, not a profile management API.

## Lifecycle

```text
ACCEPTED
   -> PROVISIONING_MEDIA
        -> WAITING_FOR_SOURCE   # WHIP or temporarily unavailable pull source
             -> STARTING
                  -> ACTIVE
                       -> RECONNECTING -> ACTIVE
                       -> STOPPING -> STOPPED
                  -> FAILED
```

The public response maps internal `PROVISIONING_MEDIA` into `STARTING` to retain
the documented state vocabulary.

Session creation persists desired state before provisioning. A pull path may
connect immediately. A push path returns while waiting and starts processing
automatically when MediaMTX reports the publisher ready.

## Generation And Reconfiguration

The session owns caller intent and history. Each generation stores:

- immutable requested request body without secrets;
- immutable resolved processing configuration;
- source type and encrypted source secret version;
- camera and location snapshot;
- built-in profile ID/version and artifact hashes;
- connector IDs/configuration versions;
- opaque ingress and optional annotated path IDs;
- configuration hash;
- desired and runtime state.

`POST /reconfigure` validates and stores generation `N+1` before stopping `N`.
Old frame and appearance results remain attributed to their original generation.
A failed replacement is visible and never rewrites generation `N` results.

## MediaMTX Controller

The controller uses the internal Control API:

```text
POST   /v3/config/paths/add/{name}
PATCH  /v3/config/paths/patch/{name}
DELETE /v3/config/paths/delete/{name}
GET    /v3/config/paths/get/{name}
GET    /v3/paths/get/{name}
```

Control API changes are runtime-only. The controller therefore reconciles
PostgreSQL desired generations against MediaMTX after either side restarts.

Rules:

- paths use opaque generation identifiers rather than names or locations;
- source credentials never appear in path names or controller logs;
- retries are idempotent and distinguish already-exists from incompatible state;
- a path is input-ready only when the active Paths API reports a readable stream;
- stale paths with no desired generation are removed after a bounded grace period;
- the Control API is available only on the internal network.

## Response

### Push Session Waiting For Source

```json
{
  "sessionId": "uuid",
  "generation": 1,
  "state": "WAITING_FOR_SOURCE",
  "profile": {"id": "face-recognition-v1", "version": 1},
  "ingest": {
    "type": "whipPush",
    "publishUrl": "https://media.example/opaque-path/whip"
  },
  "links": {
    "frames": "/api/v1/live/sessions/uuid/frames",
    "appearances": "/api/v1/live/sessions/uuid/appearances",
    "recordings": "/api/v1/live/sessions/uuid/recordings"
  },
  "outputs": {
    "recording": {"state": "waitingForSource"},
    "annotatedStream": {"state": "waitingForSource", "urls": {}}
  }
}
```

### Active Session

```json
{
  "sessionId": "uuid",
  "generation": 1,
  "state": "ACTIVE",
  "ingest": {"type": "whipPush"},
  "outputs": {
    "recording": {"state": "recording"},
    "annotatedStream": {
      "state": "ready",
      "urls": {
        "rtsp": "rtsp://media.example/annotated/opaque-path",
        "webrtc": "https://media.example/annotated/opaque-path"
      }
    }
  }
}
```

The write-only WHIP publish URL may be returned only at creation or explicit
rotation according to deployment policy. Pull URLs are never returned.

## Persistence Changes

The minimal business model contains:

- `live_session` for stable caller intent and current generation;
- `live_session_generation` for immutable requested/resolved configuration and
  runtime state;
- `live_connector` for registered destination configuration and encrypted secret;
- transition history sufficient for recovery and diagnosis.

Existing `live_camera` and `live_camera_run` behavior may be migrated into these
entities rather than duplicated indefinitely. Existing lease fencing remains the
runtime ownership mechanism.

## Stable Errors

- `LIVE_SESSION_SPEC_INVALID`;
- `LIVE_SOURCE_TYPE_UNSUPPORTED`;
- `LIVE_SOURCE_CREDENTIAL_INVALID`;
- `LIVE_PROFILE_NOT_FOUND`;
- `LIVE_CONNECTOR_NOT_FOUND`;
- `LIVE_MEDIA_PATH_FAILED`;
- `LIVE_SOURCE_TIMEOUT`;
- `LIVE_CAPACITY_EXHAUSTED`;
- `LIVE_GENERATION_CONFLICT`;
- `LIVE_START_FAILED`;
- `LIVE_RECONFIGURE_FAILED`.

## Acceptance

- OpenAPI rejects unknown and incompatible fields;
- profile resolution is deterministic and hash stable;
- RTSP pull and WHEP pull become readable internal RTSP paths;
- WHIP push returns a publish URL and auto-starts after publication;
- no source secret is returned or logged;
- MediaMTX restart recreates every desired path;
- stale and incompatible MediaMTX paths are reconciled safely;
- stop/reconfigure is idempotent and generation fenced;
- reconfigure preserves old results and replaces media paths cleanly;
- JSON-only, recording, annotated, and combined specs compile into the expected
  distinct graph/output configuration;
- API-key rejection and acceptance are contract tested;
- no legacy fixed public port or caller-selected GPU field remains in the API.
