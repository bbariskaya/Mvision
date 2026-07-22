# Configurable Camera Session API Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 2

## Goal

Replace fixed camera registration, body-less start, global config paths, fixed
ports, and implicit output behavior with a typed, versioned session API. A caller
can request detection, tracking, recognition, appearance aggregation, recording,
JSON delivery, and optional annotated media without controlling unsafe runtime
internals.

## Non-Goals

- Arbitrary GStreamer/DeepStream graphs or properties;
- caller-provided config file paths, model binaries, process arguments, or shell
  hooks;
- multi-camera placement in this phase;
- hot mutation of active processing behavior;
- raw connector destinations in normal session requests.

## Resources

### Location

Caller-owned typed business location:

```json
{
  "locationId": "uuid",
  "externalLocationId": "office-a-entrance",
  "siteId": "office-a",
  "areaId": "entrance",
  "displayName": "Office A - Entrance"
}
```

Mvision does not infer this data. Location is optional and caller scoped.

### CameraSource

Contains source type, encrypted write-only connection material, optional
location reference, caller metadata, lifecycle state, and URI fingerprint.
Responses never expose URI components or credentials.

### PipelineProfile

A profile has immutable versions. Each version contains typed platform-owned
defaults and references to approved model/tracker artifacts. Existing fixed
paths become the initial seeded profile, not caller-controlled fields.

### Connector

Registered Webhook or Kafka destination with encrypted secret material. Session
specifications contain connector IDs and versions only.

### CameraSession And SessionGeneration

The session is durable caller intent and history. Each generation contains one
immutable requested spec, resolved spec, spec hash, source/location snapshot,
worker assignment, and runtime state.

## API Surface

```text
GET    /v1/live/capabilities

POST   /v1/live/locations
GET    /v1/live/locations/{locationId}
PATCH  /v1/live/locations/{locationId}

POST   /v1/live/sources
GET    /v1/live/sources
GET    /v1/live/sources/{sourceId}
PATCH  /v1/live/sources/{sourceId}
DELETE /v1/live/sources/{sourceId}

POST   /v1/live/profiles
GET    /v1/live/profiles
GET    /v1/live/profiles/{profileId}/versions/{version}
POST   /v1/live/profiles/{profileId}/versions

POST   /v1/live/connectors
GET    /v1/live/connectors
GET    /v1/live/connectors/{connectorId}
POST   /v1/live/connectors/{connectorId}/rotate-secret
POST   /v1/live/connectors/{connectorId}/test

POST   /v1/live/sessions
GET    /v1/live/sessions
GET    /v1/live/sessions/{sessionId}
POST   /v1/live/sessions/{sessionId}/reconfigure
POST   /v1/live/sessions/{sessionId}/stop
GET    /v1/live/sessions/{sessionId}/generations
GET    /v1/live/sessions/{sessionId}/appearances
GET    /v1/live/sessions/{sessionId}/detections
GET    /v1/live/sessions/{sessionId}/recordings
```

Admin authorization is required for profile publication, connector secret
management, and placement constraints.

## Source Choice

Exactly one source variant is required:

```json
{"source": {"sourceRef": "uuid"}}
```

or, for an authorized caller:

```json
{
  "source": {
    "inline": {
      "type": "rtsp",
      "uri": "write-only",
      "locationRef": "uuid"
    }
  }
}
```

Inline credentials are encrypted before the accepted response is returned.

## Session Specification

```json
{
  "schemaVersion": 1,
  "profileRef": {"profileId": "standard-live", "version": 3},
  "source": {"sourceRef": "uuid"},
  "analytics": {
    "mode": "recognize",
    "sampling": {"mode": "every_n_frames", "value": 1},
    "detectorThreshold": 0.5,
    "recognitionThreshold": 0.62,
    "top2Margin": 0.05,
    "alignment": {"mode": "five_point"},
    "tracking": {"enabled": true, "maxGapSeconds": 1.5},
    "unknownIdentity": {
      "mode": "global_persistent",
      "minimumEvidence": 3
    }
  },
  "appearance": {"enabled": true, "mergeGapSeconds": 2.0},
  "sourcePolicy": {
    "latencyMs": 200,
    "frameTimeoutSeconds": 5,
    "reconnectIntervalSeconds": 10,
    "reconnectAttempts": -1
  },
  "recording": {
    "enabled": true,
    "format": "fmp4",
    "segmentDuration": "15m",
    "retention": "7d"
  },
  "results": {
    "mode": "appearances_and_detections",
    "connectorRefs": ["uuid", "uuid"]
  },
  "annotatedStream": {
    "enabled": true,
    "protocols": ["rtsp"],
    "osd": {
      "boundingBox": {
        "enabled": true,
        "colorMode": "identity_state",
        "knownColor": "#00FF00",
        "unknownColor": "#FF0000",
        "lineWidth": 3
      },
      "landmarks": {"enabled": true, "color": "#FFFF00"},
      "label": {
        "enabled": true,
        "fields": ["name", "cosine", "detector_confidence"]
      }
    }
  },
  "resources": {"resourceClass": "standard"}
}
```

## Typed Configuration And Validation

### Analytics Modes

- `detect`: detector output only; alignment may be `none`.
- `detect_track`: detector plus tracker; alignment may be `none`.
- `recognize`: detector, tracker, quality, model-compatible five-point
  alignment, embedding, and identity resolution.

Recognition with `alignment=none` is rejected. The API must not run a known
alignment-sensitive recognizer over unaligned crops while claiming recognition.

### Dependencies

- appearance requires tracking;
- global anonymous identity requires recognition and quality evidence;
- per-frame recognition output requires recognition mode;
- OSD fields require annotated output;
- identity-based colors require recognition output;
- recording and annotated streaming are independent;
- JSON-only sessions instantiate neither encoder nor annotated MediaMTX path.

Unknown and contradictory fields are errors. No field is silently ignored.

## Profile Resolution And Compilation

```text
platform defaults
  + exact immutable profile version
  + validated request overrides
  = immutable resolved generation spec
```

The compiler maps typed values to internal artifact references and a versioned
`StartCommand`. It allocates internal paths and ports; callers never do.

The generation stores:

- requested spec without secrets;
- resolved spec without secrets;
- exact profile and connector versions;
- model/config artifact hashes;
- capability document version;
- SHA-256 of the canonical resolved spec.

## Capabilities Contract

`GET /v1/live/capabilities` returns:

- supported session schema versions;
- analytics, alignment, tracker, and sampling modes;
- approved model/profile IDs and versions;
- numeric bounds and defaults;
- field dependency matrix;
- recording formats and duration bounds;
- result granularity and connector types;
- annotated output protocols and OSD fields;
- resource classes;
- deprecated fields and removal versions.

The response is cacheable and version identified. A client can validate forms or
requests without duplicating server rules.

## Lifecycle

```text
ACCEPTED -> ASSIGNED -> STARTING -> ACTIVE
                           |          |
                           v          v
                        FAILED   RECONFIGURING
                                      |
                                  generation+1
                                      |
                                   STARTING
```

Additional terminal/transient states: `REJECTED`, `DEGRADED`, `STOPPING`, and
`STOPPED`.

`POST /reconfigure` validates and persists the next generation before stopping
the active one. It does not rewrite old results. A failed replacement is visible
as a failed generation with a stable code; history remains intact.

## Response Contract

```json
{
  "sessionId": "uuid",
  "generation": 4,
  "state": "ACTIVE",
  "specHash": "sha256",
  "links": {
    "appearances": "/v1/live/sessions/uuid/appearances",
    "detections": "/v1/live/sessions/uuid/detections",
    "recordings": "/v1/live/sessions/uuid/recordings"
  },
  "outputs": {
    "annotatedStream": {
      "state": "ready",
      "urls": {"rtsp": "rtsp://trusted-host/path"}
    }
  }
}
```

Media URLs are absent until the downstream path is verified ready.

## Persistence

Additive business entities:

- `live_location`;
- `live_camera_source`;
- `live_pipeline_profile` and immutable profile version;
- `live_connector` and immutable connector configuration version;
- `live_session`;
- `live_session_generation`;
- session transition/audit history.

Secrets use encrypted columns or external secret references and never participate
in the spec hash.

## Error Vocabulary

- `SESSION_SPEC_FIELD_UNKNOWN`;
- `SESSION_SPEC_INCOMPATIBLE`;
- `CAPABILITY_NOT_AVAILABLE`;
- `PROFILE_VERSION_NOT_FOUND`;
- `CONNECTOR_VERSION_NOT_FOUND`;
- `SOURCE_NOT_FOUND`;
- `SOURCE_CREDENTIAL_INVALID`;
- `SESSION_CAPACITY_EXHAUSTED`;
- `SESSION_GENERATION_CONFLICT`;
- `SESSION_START_FAILED`;
- `SESSION_RECONFIGURE_FAILED`.

## Acceptance

- profile resolution is deterministic and hash stable;
- every supported/forbidden combination is contract tested;
- recognition without five-point alignment is rejected;
- inline and durable source variants compile equivalently;
- idempotency keys do not duplicate sessions;
- JSON-only compiled graphs contain no encoder/output allocation;
- annotated specs contain only declared OSD fields;
- reconfiguration increments generation and preserves history;
- secrets are absent from OpenAPI examples, responses, logs, traces, metrics,
  commands, and hashes;
- restart reconstructs durable desired session state and exact generation;
- no old fixed port/path/GPU field remains a caller-visible requirement.
