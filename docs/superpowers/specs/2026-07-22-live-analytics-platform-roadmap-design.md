# Live Analytics Platform Roadmap Design

**Status:** Approved direction
**Revised:** 2026-07-23

## Product Outcome

Mvision accepts a live stream through a typed API, analyzes selected frames with
the existing DeepStream face pipeline, and emits JSON for every processed frame.
Each frame result contains original-pixel bounding boxes, five landmarks, local
track state, identity state, and confidence values.

Callers may additionally request person appearance summaries, 15-minute source
recordings, and an annotated RTSP/WebRTC stream. Multi-camera execution begins
with isolated per-session processes rather than a shared dynamic pipeline.

## Architecture

```text
Customer MediaMTX or RTSP source
  -> RTSP/WHEP pull or WHIP push
  -> Mvision MediaMTX generation ingress
       -> optional raw fMP4 recording
       -> internal RTSP
            -> isolated DeepStream worker
                 -> frame.result JSON for every processed frame
                 -> optional appearance aggregation
                 -> direct Webhook/Kafka delivery
                 -> asynchronous PostgreSQL persistence
                 -> optional OSD/encoder
                      -> Mvision MediaMTX annotated path
                      -> RTSP + WebRTC viewer URLs
```

MediaMTX normalizes caller-facing media protocols. DeepStream consumes one
internal RTSP contract for all source variants.

## Locked Decisions

- Frame JSON is the default result; appearance summaries are optional.
- Every processed frame emits exactly one `frame.result`, including no-face
  frames with `faces: []`.
- Processing cadence is controlled by typed sampling configuration.
- Geometry is returned in original source-frame pixels.
- The supported source variants are `rtspPull`, `whepPull`, and `whipPush`.
- A push session returns a WHIP publish URL and waits for media automatically.
- Session configuration uses built-in versioned profiles plus typed overrides.
- Arbitrary GStreamer properties, model paths, GPU arguments, ports, and shell
  commands are forbidden.
- Recognition always uses five-point alignment.
- Tracker IDs are generation-local; known and persistent anonymous `faceId`
  values are global.
- Direct connector delivery is the low-latency path. Persistence is separate and
  asynchronous; Webhook delivery does not claim crash-safe at-least-once.
- Connector destinations are registered and referenced by `connectorRef`.
- Recording is optional, records the unannotated ingress, and defaults to
  15-minute fMP4 segments when enabled.
- Annotated output is optional and returns simple RTSP and WebRTC URLs.
- Reconfiguration creates an immutable generation and controlled restart.
- Initial multi-camera execution uses one native process per active session.
- API authentication uses a deployment API key; OIDC/RBAC is deferred.

## Delivery 1: Session API And Media Ingress

Deliver:

- `POST /api/v1/live/sessions` with typed source, profile, overrides, location,
  and output selection;
- session get/list/stop/reconfigure and capability discovery;
- simple API-key authentication;
- MediaMTX path controller for RTSP pull, WHEP pull, and WHIP push;
- generation-scoped internal RTSP paths;
- `WAITING_FOR_SOURCE`, start, active, reconnect, stop, and failure state;
- PostgreSQL desired state and MediaMTX reconciliation after restart;
- compiled generation configuration passed through a versioned native command.

Gate:

- all three source contracts pass against MediaMTX fixtures;
- push publication requires no manual worker restart;
- reconnect and MediaMTX restart recover without false `ACTIVE` state;
- no secret appears in responses, logs, traces, metrics, or process arguments.

## Delivery 2: Frame JSON And Optional Appearance

Deliver:

- separate stream PTS and observed UTC semantics;
- one `frame.result` per processed frame;
- original-pixel bbox and landmark output;
- local track lifecycle with native expiry events;
- known, pending, unknown, anonymous, and new-anonymous transitions;
- global persistent anonymous creation/reuse under quality gates;
- optional appearance started/ended aggregation;
- direct Webhook/Kafka dispatch through registered connectors;
- independent asynchronous PostgreSQL persistence and pull APIs;
- bounded connector backpressure and observable frame drops/rejections.

Gate:

- deterministic fixtures prove frame count, frame order, empty frames, geometry,
  identity transitions, track expiry, and optional duration summaries;
- slow/offline connectors do not reduce inference progress;
- event IDs remain stable across in-process retry;
- no embedding or aligned crop enters external JSON.

## Delivery 3: Optional Media Outputs

Deliver:

- optional raw ingress recording through MediaMTX;
- 15-minute production fMP4 segmentation and shorter test segmentation;
- completed-segment metadata, persistent retention, and optional MinIO upload;
- optional OSD/encoder/publisher graph;
- typed bbox, landmark, color, line-width, and label controls;
- generation-scoped annotated MediaMTX path;
- ready-state RTSP and WebRTC URLs;
- independent recording and annotated-output failure state.

Gate:

- JSON-only sessions instantiate no recording or annotated branch;
- one real 15-minute recording rollover finalizes successfully;
- viewer stall and publisher restart do not stop JSON or inference;
- output URLs are absent until MediaMTX reports a readable path.

## Delivery 4: Isolated Multi-Camera

Deliver:

- removal of the single-running-camera database constraint;
- removal of fixed public worker RTSP ports;
- fixed-size worker pool using existing PostgreSQL claim/lease fencing;
- one isolated native process per active session;
- configured concurrent-session admission limit;
- session-scoped paths, connector queues, recording roots, and metrics;
- independent restart and teardown.

Gate:

- at least three simultaneous fixture cameras remain isolated;
- killing, disconnecting, or stalling one session does not change another;
- capacity is rejected before GPU work rather than failing with OOM;
- repeated concurrent start/stop has bounded threads, file descriptors, request
  pads, sockets, and GPU memory.

## Existing Code Reused

- `backend/pipeline/src/live_pipeline.cpp`: DeepStream detector, tracker,
  alignment, ArcFace, quality evidence, reconnect, and OSD foundations;
- `backend/app/services/live_identity_service.py`: temporal identity state;
- `backend/app/services/video_identity_voting_service.py`: threshold and top-2
  margin concepts, extended for anonymous matching;
- `backend/app/services/live_supervisor.py`: run claiming, lease fencing, native
  lifecycle, and command/event transport;
- PostgreSQL, Qdrant, and MinIO as existing persistence boundaries.

## Required Corrections Before Expansion

- PTS is currently treated as Unix time and must be separated from observed UTC.
- Native track expiry is defined in the protocol but is not emitted.
- Live unknown results currently have no global anonymous `faceId`.
- The native graph currently always creates its encoder/RTSP output branch.
- A full identity queue currently drops critical evidence events.
- One database index permits only one running camera.
- Worker output uses fixed UDP/RTSP ports and an embedded RTSP server.

## Reference Adoption

| Reference | Adopt | Do not adopt |
|---|---|---|
| WJLI DeepStream ReID | source-scoped metadata, tee and nonblocking fast-path concepts | per-frame embeddings, silent ZMQ loss, simple global-ID gallery |
| Yakhyo YOLOv8 Face | detector/landmark/NMS parity fixtures | Python ONNX data plane |
| gst-nvinfer-custom | landmark metadata and alignment diagnostics | replacement of NVIDIA system libraries |
| DeepStream-Yolo-Face | current DeepStream parser/export/config comparison | demo application architecture |
| Abdirayimov multi-stream | batched alignment/encoding and dynamic-source tests | shared pipeline before isolated-camera acceptance |
| Limitless surveillance | simple control API ergonomics and task isolation | OpenCV capture and Celery video data plane |

Repositories without an explicit license in the reviewed checkout are conceptual
or black-box test references only. Source is copied only from compatible licensed
references with required attribution.

## Deferred Work

- exact recording-sample sidecars and zero-frame recording joins;
- PostgreSQL outbox, delivery replay, dead-letter management, and crash-safe
  at-least-once Webhook delivery;
- profile publication APIs and arbitrary caller-created profiles;
- OIDC, RBAC, multi-tenant policy, generated SDKs, and public deprecation policy;
- dynamic GPU resource classes and a general scheduler;
- shared DeepStream dynamic batching;
- cross-camera body ReID and trajectory stitching;
- caller-supplied plugins, model binaries, or executable code.

## Documentation Set

- `requirements/live-streaming-requirements.md`
- `docs/superpowers/specs/2026-07-22-configurable-camera-session-api-design.md`
- `docs/superpowers/specs/2026-07-22-live-frame-json-output-design.md`
- `docs/superpowers/specs/2026-07-22-optional-recording-design.md`
- `docs/superpowers/specs/2026-07-22-optional-annotated-stream-design.md`
- `docs/superpowers/specs/2026-07-22-isolated-multi-camera-design.md`

The former exact-frame recording, durable-outbox-first delivery, general
scheduler, and hardening/SDK documents are not prerequisites for these four
deliveries.
