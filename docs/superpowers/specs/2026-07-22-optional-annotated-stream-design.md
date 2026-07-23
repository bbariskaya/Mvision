# Optional Annotated Stream Design

**Status:** Approved direction
**Delivery:** 3 - Optional Media Outputs
**Revised:** 2026-07-23

## Goal

Create an annotated media branch only when requested. Publish the result to a
generation-scoped MediaMTX path and return simple RTSP and WebRTC viewer URLs
without changing frame JSON, identity, appearance, or recording behavior.

## Locked Behavior

- Annotated output defaults to disabled.
- A JSON-only session creates no OSD, encoder, payloader, publisher, MediaMTX
  annotated path, or viewer URL.
- OSD fields are typed and generation scoped.
- Viewer authentication is not required for the target deployment.
- URLs are returned only after MediaMTX reports a readable path.
- A viewer, encoder, or publisher failure never blocks frame JSON or inference.
- Recording captures the unannotated ingress and is independent from this branch.

## Native Graph

Disabled:

```text
decode -> detector -> tracker -> alignment/ArcFace -> frame JSON sink
```

Enabled:

```text
decode -> detector -> tracker -> alignment/ArcFace -> tee
                                                  -> frame JSON sink
                                                  -> bounded leaky queue
                                                       -> OSD
                                                       -> H.264 encoder
                                                       -> parser/payloader
                                                       -> MediaMTX publisher
```

The output queue is downstream-leaky. Dropping an annotated frame is preferable
to delaying analytics.

The first implementation may retain the currently proven RTP/RTSP publishing
mechanism internally, but the public output terminates at MediaMTX rather than an
embedded per-worker public RTSP server. This removes fixed public worker ports
and allows one MediaMTX path to expose both RTSP and WebRTC.

## Session Configuration

```json
{
  "annotatedStream": {
    "enabled": true,
    "boundingBox": {
      "enabled": true,
      "colorMode": "identityState",
      "fixedColor": "#00FF00",
      "knownColor": "#00FF00",
      "anonymousColor": "#FFA500",
      "pendingColor": "#FFFF00",
      "unknownColor": "#FF0000",
      "lineWidth": 3
    },
    "landmarks": {
      "enabled": true,
      "color": "#FFFF00",
      "radius": 2
    },
    "labels": {
      "enabled": true,
      "fields": [
        "name",
        "status",
        "trackId",
        "recognitionConfidence",
        "detectorConfidence"
      ]
    }
  }
}
```

Encoder codec, baseline latency tuning, GOP, and bitrate are profile-owned in the
first version. They are not exposed merely because GStreamer supports them.

Colors use validated RGBA/hex values and numeric fields use capability bounds.
Unknown fields are errors.

## Dependencies

- boxes require detection output;
- track ID labels require tracking;
- identity-state colors, name, and recognition confidence require recognition;
- landmarks require detector landmark output;
- detection-only sessions may render boxes, landmarks, and detector confidence;
- disabling a visual layer does not disable analytics needed by frame JSON;
- OSD selection never changes the external frame JSON schema.

## Identity Timing

Identity resolution is asynchronous. Pending tracks use the pending style. After
a generation-fenced identity assignment arrives, later output frames use the
accepted known/anonymous/new-anonymous style and label.

Previously encoded frames are not rewritten. An identity reset increments its
epoch and returns the track to the appropriate pending/unknown style.

## MediaMTX Path Lifecycle

The Session Controller creates an opaque annotated publisher path before worker
output starts.

```text
DISABLED
  -> PROVISIONING
       -> WAITING_FOR_PUBLISHER
            -> READY
            -> FAILED
       -> FAILED
```

The worker receives an internal publisher target through its resolved generation
command. MediaMTX Control API and internal publisher details are not caller
fields.

Stale generation paths are removed after worker teardown and a bounded viewer
grace period. MediaMTX restart reconciliation recreates the desired path; the
worker publisher reconnects without restarting source inference where possible.

## URL Contract

```json
{
  "annotatedStream": {
    "state": "ready",
    "generation": 4,
    "urls": {
      "rtsp": "rtsp://media.example/annotated/opaque-path",
      "webrtc": "https://media.example/annotated/opaque-path"
    }
  }
}
```

Externally returned URLs use configured public origins, never container names.
The API does not return MediaMTX Control API, internal RTSP, UDP, or publisher
URLs.

## Output Readiness

The worker emitting `output_ready` is necessary but not sufficient. The Session
Controller verifies MediaMTX active path state and a bounded decode probe before
publishing URLs.

Readiness is generation fenced:

- an old worker cannot make a new generation ready;
- a path with no active publisher has no viewer URLs;
- a codec/caps mismatch produces a stable output failure;
- session `ACTIVE` may coexist with annotated output `FAILED`.

## Backpressure And Recovery

- a bounded leaky queue isolates output from the inference branch;
- output drops have counters and do not alter frame-result sequence;
- viewer disconnect does not stop the publisher;
- publisher reconnect is independent from source reconnect;
- encoder/publisher failure marks only annotated output failed/degraded;
- repeated start/stop releases tee request pads, encoder resources, sockets, and
  MediaMTX paths;
- reconfiguration replaces the generation path rather than mutating it in place.

## Observability

Metrics include bounded output state, encoded frames, output frames, dropped
frames, publisher reconnect count, output FPS, and encoder latency. Session IDs,
paths, person names, and face IDs are not metric labels.

## Stable Errors

- `LIVE_ANNOTATED_OPTION_INVALID`;
- `LIVE_ANNOTATED_CAPABILITY_UNAVAILABLE`;
- `LIVE_ANNOTATED_PATH_FAILED`;
- `LIVE_ANNOTATED_ENCODER_FAILED`;
- `LIVE_ANNOTATED_PUBLISHER_FAILED`;
- `LIVE_ANNOTATED_NOT_READY`.

## Acceptance

### JSON-Only

- no output tee branch elements are created;
- no encoder, payloader, publisher, or annotated MediaMTX path exists;
- no viewer URL is returned;
- frame JSON count and content remain complete.

### Detection Output

- requested boxes and landmarks render;
- identity-only labels and colors are rejected;
- RTSP and WebRTC clients decode the output.

### Recognition Output

- pending, known, anonymous, and unknown styles follow current assignments;
- selected labels update without changing JSON identity decisions;
- disabled visual layers are absent;
- output dimensions match the declared source/output contract.

### Resilience

- URLs remain absent until MediaMTX and decode readiness pass;
- a stalled viewer does not reduce generated frame JSON or inference counters;
- publisher restart recovers without source restart;
- output failure leaves JSON, appearance, and recording components operational;
- MediaMTX restart reconciles the path and restores URLs;
- 50 output start/stop cycles show bounded file descriptors, threads, request
  pads, sockets, and GPU memory;
- no credential, embedding, internal path, or unauthorized field is rendered or
  returned.
