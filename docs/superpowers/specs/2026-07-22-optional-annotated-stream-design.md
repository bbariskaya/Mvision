# Optional Annotated Stream Design

**Status:** Draft for user review  
**Phase:** Live Analytics Platform Phase 5

## Goal

Create an annotated media stream only when requested by SessionSpec. Return a
ready viewer URL through the API while keeping recognition, recording, JSON
results, and appearance aggregation independent from viewer behavior.

## Locked Behavior

- Annotated output is optional and disabled by default.
- JSON-only sessions instantiate no encoder, RTP payloader, publisher, MediaMTX
  annotated path, or output URL.
- OSD configuration is typed and generation scoped.
- Reconfiguration creates a new generation; active graph behavior is not
  silently mutated.
- Viewer backpressure never blocks inference or recording.

## Output Graph

When disabled:

```text
decode -> inference -> result callbacks
```

When enabled:

```text
decode -> inference -> bounded leaky output queue
                    -> OSD
                    -> H.264 encoder
                    -> rtph264pay
                    -> rtspclientsink
                    -> MediaMTX annotated/{sessionId}/{generation}
```

Official MediaMTX guidance recommends GStreamer RTSP publishing through
`rtspclientsink`. The installed DeepStream image must prove this element and TCP
publishing before implementation acceptance.

MediaMTX exposes one published path to declared readable protocols. RTSP is the
required first protocol. HLS/WebRTC URLs are returned only if current runtime
capabilities, authentication, codec profile, and deployment exposure support
them.

## Session Specification

```json
{
  "annotatedStream": {
    "enabled": true,
    "protocols": ["rtsp"],
    "video": {
      "codec": "h264",
      "bitrateKbps": 4000,
      "gopFrames": 30
    },
    "osd": {
      "boundingBox": {
        "enabled": true,
        "colorMode": "identity_state",
        "fixedColor": null,
        "knownColor": "#00FF00",
        "anonymousColor": "#FFA500",
        "unknownColor": "#FF0000",
        "lineWidth": 3
      },
      "landmarks": {
        "enabled": true,
        "color": "#FFFF00",
        "radius": 2
      },
      "label": {
        "enabled": true,
        "fields": ["name", "identity_status", "cosine", "detector_confidence"],
        "fontScale": 1.0,
        "textColor": "#FFFFFF",
        "backgroundColor": "#000000AA"
      }
    }
  }
}
```

Caller colors use validated RGBA hex values. Numeric bounds come from
capabilities. Unsupported fields and contradictory combinations are rejected.

## Processing Dependencies

- bbox rendering requires detector output;
- identity-state color and name/cosine labels require recognition mode;
- landmarks require detector landmark output but not necessarily recognition;
- five-point alignment is an analytics input option, not an OSD requirement;
- detection-only sessions can render boxes/landmarks without identity labels;
- disabling one visual layer does not disable its analytics producer if another
  requested result needs that producer.

## MediaMTX Path Lifecycle

The Session Controller provisions a publisher path before worker start. The path
is internal and generation scoped. The worker receives short-lived publisher
credentials or an internal authenticated URL through a secret-safe channel.

States:

```text
DISABLED
PROVISIONING -> WAITING_FOR_PUBLISHER -> READY
                     |                   |
                     v                   v
                   FAILED             DEGRADED
```

The API returns viewer URLs only at `READY`. Stale generation URLs are revoked or
become unavailable after bounded grace. Path deletion waits for worker teardown
and viewer disconnect policy.

## URL Contract

```json
{
  "annotatedStream": {
    "state": "ready",
    "generation": 4,
    "urls": {
      "rtsp": "rtsp://trusted-host/live/session/generation"
    },
    "expiresAt": null
  }
}
```

Externally exposed URLs use configured trusted public origins, never container
hostnames. Authentication tokens are bounded and not persisted in logs. HLS or
WebRTC URLs can use bounded signed/session credentials when enabled.

## Backpressure And Failure Isolation

- A bounded downstream-leaky queue separates OSD/encoder from inference.
- Dropped output frames increment bounded metrics but do not drop analytics.
- Publisher reconnect is independent from source reconnect.
- Encoder/publisher failure marks annotated output failed/degraded; session
  analytics may remain active.
- A stalled or disconnected viewer cannot block publisher/inference threads.
- Repeated output start/stop releases encoder, request pads, sockets, and
  MediaMTX path state.

## Security

- Publisher and viewer credentials never enter rendered labels or result events.
- Caller-provided label text is not supported in the first version; only selected
  safe fields render.
- Names are rendered only when caller/session authorization permits PII output.
- MediaMTX publish paths are unguessable and authenticated on non-isolated
  networks.
- Control API remains internal.

## Observability

Metrics include bounded output state, encoded/output/dropped frame counters,
publisher reconnect count, output FPS, and encoder latency. Session/path IDs are
trace attributes or logs only after privacy policy; never metric labels.

## Acceptance Matrix

### JSON-Only

- no encoder element is created;
- no `rtspclientsink` or RTP output is created;
- no MediaMTX annotated path exists;
- no viewer URL is returned;
- JSON/appearance results remain complete.

### Detection-Only Annotated

- boxes and optional landmarks render;
- identity labels/colors are rejected;
- output decodes through RTSP.

### Recognition Annotated

- requested known/anonymous/unknown colors render;
- enabled label fields update from current analytics state;
- disabled layers are absent;
- output dimensions match source contract.

### Resilience

- five-frame decode succeeds for every enabled protocol;
- stalled viewer does not reduce inference counter advancement;
- output publisher restart recovers without source restart;
- output failure leaves appearance/recording active;
- generation reconfigure replaces path and invalidates stale URL;
- 50 output start/stop cycles show stable file descriptors, threads, request
  pads, and GPU memory within measured tolerance;
- no secret or unauthorized PII appears in URL, log, trace, metric, or label.
