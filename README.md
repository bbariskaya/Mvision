# Mvision

Mvision is a GPU-accelerated face-recognition platform for images, uploaded
videos, and a single-camera RTSP livestream milestone. The current system
supports image enrollment/recognition and asynchronous uploaded-video
recognition. Phase 3 Packets 1-2 add the livestream capability gate, secure
camera configuration, durable camera/run/event state, camera API contracts,
strict duplex protocol, and bounded native track evidence state. Packet 3 Tasks
7-10 add verified native RTSP ingest and inference, two-layer reconnect,
bounded native worker transport, fenced Python supervision, and live identity
epochs with durable events/snapshots. Annotated RTSP output and the self-hosted
OpenTelemetry/Grafana stack are implemented; long-duration soak and the remaining
observability fault/overhead gates are still pending.

## Delivery Status

| Capability | Status | Notes |
|---|---|---|
| Image enrollment and recognition | Implemented | FastAPI to persistent GPU workers over Unix sockets. |
| Uploaded-video recognition | Implemented | PostgreSQL jobs, native DeepStream worker, track-level identity voting. |
| Friends full-video validation | Verified | 6,665 frames processed and annotated output generated. |
| Single-camera RTSP livestream | Packet 4 identity verified | Runtime/control-plane contracts, framed protocol, bounded queues, `nvurisrcbin` NVDEC/NVMM ingest, YOLOv8-Face/NvDCF/ArcFace inference, reconnect, teardown, secret-safe supervision, logical identity epochs, cooldown, durable events, and strict live snapshots are implemented. Annotated output remains. See `docs/superpowers/plans/2026-07-21-single-camera-livestream.md`. |
| OpenTelemetry and Grafana observability | Platform running; final gates pending | Collector, Prometheus, Loki, Tempo, provisioned dashboards, bounded metrics, error traces, correlated logs, privacy tests, and a real acceptance verifier are implemented. Fault isolation, retention lifecycle proof, overhead A/B, and soak remain. |
| Dynamic multi-camera runtime | Later Phase 3 packet | Starts after the single-camera milestone is stable. |
| Cross-camera body ReID | Later Phase 3 packet | Requires separate topology, timestamp, model, and ReID acceptance. |

## Live Observability Check

Grafana binds server loopback on `127.0.0.1:3001`. From an operator machine,
open a tunnel and browse to `http://localhost:3001`:

```bash
ssh -N -L 3001:127.0.0.1:3001 user@10.1.60.230
```

The `Live Camera Operations` dashboard shows worker/runtime health, FPS,
recognition throughput and yield, compact anomaly stats, recent error traces,
and trace-correlated logs. To test Tempo and Loki without crashing or stopping
the media pipeline, run this on the server:

```bash
TRACE_ID="$(docker exec mvision-live-worker python3 -m app.observability.smoke)"
GRAFANA_PASSWORD="$(docker exec mvision-grafana-1 printenv GF_SECURITY_ADMIN_PASSWORD)" \
  PYTHONPATH=backend uv run --directory backend python scripts/verify_live_observability.py \
  --trace-id "$TRACE_ID" --grafana-url http://127.0.0.1:3001
```

Run the smoke check while the camera runtime is `ACTIVE`; an intentionally
stopped or reconnecting camera correctly fails the live-FPS gate. The verifier
performs bounded polling for Collector tail-sampling and must print
`PASS` for dashboard, Prometheus, Tempo, and Loki. The synthetic record uses the
stable `OBSERVABILITY_SMOKE_TEST` code and never injects a media failure. In
Grafana, selecting its TraceID opens Tempo; `Logs for this span` returns the safe
Loki record, and the log TraceID links back to the same trace.

## System At A Glance

The platform is split into a control plane and a GPU data plane. Python owns
HTTP contracts, durable state, identity decisions, and storage. C++ owns video
decode, DeepStream metadata, tracking, face alignment, inference, and live
rendering.

```text
                              CONTROL PLANE

 Browser / API client
         │
         ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ FastAPI + Pydantic                                          │
 │  • validation and public contracts                          │
 │  • camera/video job commands                                │
 │  • identity lifecycle and threshold policy                  │
 │  • result and event queries                                 │
 └───────────────┬──────────────────────┬───────────────────────┘
                 │                      │
        ┌────────▼────────┐    ┌────────▼────────┐
        │ PostgreSQL 16   │    │ Qdrant          │
        │ durable state   │    │ 512-D cosine    │
        │ jobs/events     │    │ face gallery    │
        └────────┬────────┘    └─────────────────┘
                 │
        ┌────────▼────────┐
        │ MinIO           │
        │ face evidence   │
        │ videos/snapshots│
        └─────────────────┘

                               GPU DATA PLANE

 ┌──────────────────────────────────────────────────────────────┐
 │ C++17 + GStreamer + NVIDIA DeepStream 9 + CUDA + TensorRT    │
 │ decode → detect → track → align → embed → metadata → output │
 └──────────────────────────────────────────────────────────────┘
```

## Current Image Pipeline

Image requests use persistent GPU workers. JPEG bytes cross a Unix socket once;
decoded frames never move through the API process.

```text
 POST /api/v1/faces/recognize or /enroll
                 │
                 ▼
 ┌────────────────────────┐       framed MessagePack
 │ FastAPI service layer  │ ───────────────────────────┐
 └────────────────────────┘                            │
                                                       ▼
                                  ┌────────────────────────────┐
                                  │ persistent C++ GPU worker  │
                                  │                            │
 JPEG ─► appsrc ─► decode ─► NVMM ─► YOLOv8-Face PGIE         │
                                  │          │                 │
                                  │          ▼                 │
                                  │ five landmarks            │
                                  │          │                 │
                                  │          ▼                 │
                                  │ GPU 5-point alignment      │
                                  │          │                 │
                                  │          ▼                 │
                                  │ ArcFace R50 SGIE           │
                                  └──────────┬─────────────────┘
                                             │ 512-D embedding
                                             ▼
                                   Qdrant + identity policy
```

## Current Uploaded-Video Pipeline

Uploaded videos are durable jobs. The tracker sees the complete decoded stream;
identity resolution happens at canonical-track level rather than once per frame.

```text
 Upload ─► ffprobe ─► MinIO ─► PostgreSQL video_job
                                      │
                                      ▼ claim + lease
                            ┌─────────────────────────┐
                            │ Python video worker     │
                            └────────────┬────────────┘
                                         │ starts native process
                                         ▼
 file ─► uridecodebin ─► nvstreammux ─► YOLOv8-Face ─► NvDCF
                                                           │
                                                           ▼
                                                GPU 5-point alignment
                                                           │
                                                           ▼
                                                    ArcFace R50
                                                           │
                                              framed track events
                                                           ▼
                                track reconciliation + named-only voting
                                                           │
                                    PostgreSQL + Qdrant + MinIO results
```

The verified video decision path uses quality-ranked observations, named-gallery
candidates, an absolute threshold, and a top-1/top-2 margin. Anonymous gallery
entries cannot suppress named candidates.

## Approved Single-Camera Livestream Target

### Scope Boundary

The first live milestone supports exactly one active RTSP camera per live worker.
It includes durable camera commands, reconnect, track-level face decisions,
evidence events, health metrics, and annotated RTSP output. It intentionally does
not include dynamic multi-camera batching or cross-camera body ReID.

### Complete Live Data Path

```text
                                      RTSP INPUT

 rtsp://camera ──► ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                   │ nvurisrcbin  │ ─► │ nvvideoconv │ ─► │ nvstreammux  │
                   │ NVDEC        │    │ NVMM / NV12  │    │ batch-size=1 │
                   │ reconnect    │    └──────────────┘    │ live-source=1│
                   └──────────────┘                         └──────┬───────┘
                                                                  │
                                                                  ▼
                    ┌────────────────────────────────────────────────────────┐
                    │            DEEPSTREAM FACE PIPELINE                    │
                    │                                                        │
                    │ ┌──────────────┐  ┌─────────────┐  ┌────────────────┐ │
                    │ │ nvinfer PGIE │─►│ NvDCF       │─►│ quality gates  │ │
                    │ │ YOLOv8-Face  │  │ local track │  │ geometry/photo │ │
                    │ │ bbox + 5 kps │  │ object_id   │  │ reject reasons │ │
                    │ └──────────────┘  └─────────────┘  └───────┬────────┘ │
                    │                                             │          │
                    │                                             ▼          │
                    │ ┌────────────────┐  ┌──────────────┐  ┌─────────────┐ │
                    │ │ nvdspreprocess │─►│ nvinfer SGIE│─►│ track bank  │ │
                    │ │ GPU 5-point    │  │ ArcFace R50 │  │ best samples│ │
                    │ │ 112×112 align  │  │ 512-D FP16  │  │ time spaced │ │
                    │ └────────────────┘  └──────────────┘  └──────┬──────┘ │
                    └───────────────────────────────────────────────┼────────┘
                                                                    │
                                                    TrackEvidence event
                                                                    ▼
                    ┌────────────────────────────────────────────────────────┐
                    │            PYTHON IDENTITY DECISION                    │
                    │                                                        │
                    │  Qdrant top-k ─► named identities only ─► threshold   │
                    │                                         └─► top-2 gap │
                    │                                                        │
                    │    ambiguous / weak ─► Unknown                         │
                    │    strong + clear   ─► Known(name, faceId, score)       │
                    └──────────────────────────────┬─────────────────────────┘
                                                   │ IdentityAssignment
                                                   ▼
                    ┌────────────────────────────────────────────────────────┐
                    │              LIVE OUTPUT BRANCH                        │
                    │                                                        │
                    │ label probe ─► nvdsosd ─► nvvideoconvert ─► H.264     │
                    │               bbox/name/score/landmarks       encoder  │
                    │                                              │         │
                    │                                              ▼         │
                    │                                    rtph264pay/UDP      │
                    │                                              │         │
                    │                                              ▼         │
                    │                                    GstRtspServer       │
                    └──────────────────────────────────────────────┬─────────┘
                                                                   │
                                                                   ▼
                                            rtsp://host:8554/live/<cameraId>
```

### Why The Decision Leaves C++ And Comes Back

DeepStream owns frame-rate-sensitive work, but the source of truth for enrolled
identities is Qdrant plus PostgreSQL. The worker therefore uses a duplex framed
MessagePack channel:

```text
 C++ live worker                              Python live worker
 ────────────────────────────────────────────────────────────────────────────
 state / metrics             ───────────────► persist runtime health
 quality TrackEvidence       ───────────────► Qdrant candidate search
                                            threshold + margin + cooldown
 OSD label map               ◄─────────────── IdentityAssignment
 graceful pipeline shutdown ◄─────────────── Stop command
```

The GStreamer probe never calls HTTP, PostgreSQL, Qdrant, or MinIO. Probe code
only updates native track state and attempts a non-blocking enqueue. A dedicated
writer thread serializes events. This prevents a slow database or network from
stalling decode and inference.

### Stream Lifecycle

The native worker, not the HTTP router, is the source of truth for runtime state.
PostgreSQL stores commands and the latest reported state so API restarts do not
lose operator intent.

```text
                         POST /start
                              │
                              ▼
                        ┌────────────┐
                        │ STARTING   │
                        └─────┬──────┘
                              │ first valid frame
                              ▼
                        ┌────────────┐
             ┌─────────►│ ACTIVE     │◄──────────┐
             │          └─────┬──────┘           │
             │                │ no data          │ valid frame
             │                ▼                  │
             │          ┌────────────┐           │
             └──────────│ RECONNECTING│───────────┘
                        └─────┬──────┘
                              │ attempts exhausted / fatal error
                              ▼
                        ┌────────────┐
                        │ FAILED     │
                        └────────────┘

 POST /stop from STARTING, ACTIVE, RECONNECTING, or FAILED
                              │
                              ▼
                        ┌────────────┐
                        │ STOPPING   │
                        └─────┬──────┘
                              ▼
                        ┌────────────┐
                        │ STOPPED    │
                        └────────────┘
```

DeepStream 9 `nvurisrcbin` supplies the first reconnect layer through
`rtsp-reconnect-interval`, `rtsp-reconnect-attempts`, `latency`, and
`drop-on-latency`. A frame watchdog supplies the second layer: it reports stale
input, moves runtime state to `RECONNECTING`, and rebuilds the source/pipeline if
the plugin cannot recover.

### Face Quality And Temporal Evidence

Not every detected face is allowed to vote. Each observation receives explicit
quality metrics and rejection reasons.

| Gate | Initial configurable default | Purpose |
|---|---:|---|
| Detector confidence | `0.50` | Reject weak detector outputs. |
| Minimum face side | `60 px` | Avoid embeddings from tiny faces. |
| Maximum clipped area | `10%` | Reject faces cut by frame borders. |
| Minimum landmark confidence | `0.50` | Reject unreliable eye/nose/mouth points. |
| Maximum absolute yaw | `45°` | Reject strong side profiles initially. |
| Maximum absolute pitch | `35°` | Reject strong up/down views initially. |
| Maximum absolute roll | `30°` | Reject heavily tilted faces initially. |
| Brightness range | `35..220` | Reject severe under/overexposure. |
| Laplacian variance | `80` | Reject blurred face crops. |
| Observation spacing | `200 ms` | Prevent nearly identical consecutive votes. |
| Evidence window | best `10` | Bound memory and retain viewpoint diversity. |
| Minimum evidence | `3` observations and `0.5 s` | Avoid one-frame identity decisions. |

These are starting values, not universal truths. Metrics and rejection histograms
must be collected on deployment footage before tightening them.

```text
 detected face
      │
      ▼
 geometry gates ──reject──► quality counter only
      │ pass
      ▼
 photometric gates ─reject─► quality counter only
      │ pass
      ▼
 ArcFace embedding
      │
      ▼
 insert into bounded, time-spaced track bank
      │
      ├── insufficient evidence ─► Pending label
      │
      ▼
 aggregate best observations ─► Python identity decision
      │
      ├── winner below threshold ─► Unknown
      ├── winner-runner gap too low ─► Unknown
      └── strong clear winner ─► Known; freeze label for track lifetime
```

### Backpressure Policy

Live video must remain live. Queues are bounded and policy is explicit:

| Data | Policy when full |
|---|---|
| Metrics | Replace the older pending metrics sample. |
| Repeated evidence for same track | Coalesce to the newest higher-quality evidence. |
| State transition | Retain; a worker unable to report state becomes degraded/failed. |
| PostgreSQL event notification | Durable row remains authoritative; notification may be lost. |
| WebSocket subscriber | Drop oldest subscriber message and increment a drop counter. |
| Video output queue | Use downstream-leaky queue so a slow viewer does not block inference. |

### Live Persistence

```text
                        ┌──────────────────────────┐
 camera command/state ─►│ PostgreSQL live_camera  │
                        └──────────────────────────┘

 Known/Unknown event ───► PostgreSQL live_detection_event
            │
            ├───────────► MinIO live/<cameraId>/<eventId>/face.jpg
            │
            └───────────► existing face identity/sample lifecycle

 512-D identity query ──► Qdrant enrolled face samples
```

RTSP credentials are write-only at the API boundary. The target design stores
the URI using authenticated encryption with `LIVE_URI_ENCRYPTION_KEYS`, uses a
separate `LIVE_URI_FINGERPRINT_KEY` for duplicate detection, never returns the
URI, and redacts userinfo/query/host secrets from logs and errors. Plaintext URI
is sent to the native process in a framed stdin command, never in argv or the
process environment.

### Planned Live API

| Method | Endpoint | Result |
|---|---|---|
| `POST` | `/api/v1/cameras` | Register one encrypted RTSP source. |
| `GET` | `/api/v1/cameras` | List sanitized camera records and runtime state. |
| `GET` | `/api/v1/cameras/{cameraId}` | Camera configuration and latest health. |
| `POST` | `/api/v1/cameras/{cameraId}/start` | Set durable desired state to running. |
| `POST` | `/api/v1/cameras/{cameraId}/stop` | Request idempotent graceful stop. |
| `DELETE` | `/api/v1/cameras/{cameraId}` | Stop and soft-delete the camera. |
| `GET` | `/api/v1/cameras/{cameraId}/events` | Paginated durable Known/Unknown events. |
| `GET` | `/api/v1/cameras/{cameraId}/events/{eventId}/snapshot` | Retrieve evidence JPEG. |
| `WS` | `/api/v1/live/events` | Best-effort low-latency event notifications. |

Only one camera may have desired state `running` in the first milestone. A second
start request returns `409 LIVE_CAMERA_LIMIT_REACHED` instead of silently
stopping the existing camera.

## Technology Stack

### GPU And Media

| Technology | Role |
|---|---|
| NVIDIA DeepStream 9 | GPU video analytics graph and metadata model. |
| GStreamer | Pipeline states, bins, pads, queues, bus messages, RTP/RTSP plumbing. |
| NVDEC / `nvurisrcbin` | Hardware decode, jitter buffering, RTSP reconnect. |
| `nvstreammux` | Live batch formation; batch size one for the first milestone. |
| TensorRT FP16 | Optimized YOLOv8-Face and ArcFace engine execution. |
| `nvinfer` PGIE | Full-frame face detection with five landmarks. |
| NvDCF / `nvtracker` | Local per-camera track IDs and short occlusion continuity. |
| `nvdspreprocess` | Custom CUDA five-point similarity alignment to `112×112`. |
| `nvinfer` SGIE | ArcFace R50 512-dimensional embedding extraction. |
| CUDA C++ | Alignment and planned photometric quality kernels. |
| `nvdsosd` | Bounding boxes, labels, scores, and landmark overlay. |
| `nvv4l2h264enc` | Hardware H.264 encoding for live output. |
| GstRtspServer | Serves annotated RTSP output. |

### Backend And Storage

| Technology | Role |
|---|---|
| Python 3.12 | Control-plane and worker orchestration. |
| FastAPI `>=0.115` | HTTP/WebSocket API. |
| Pydantic 2 | Typed request/response and environment settings. |
| SQLAlchemy 2 + psycopg 3 | Async PostgreSQL persistence and worker leases. |
| PostgreSQL 16 | Durable camera commands, state, jobs, identities, and events. |
| Qdrant `>=1.12` | Cosine search over normalized 512-D ArcFace embeddings. |
| MinIO `>=7.2` | Face samples, videos, and live evidence snapshots. |
| MessagePack | Bounded binary protocol between Python and native workers. |
| Alembic | Additive database migrations. |
| `cryptography` | Planned encryption for stored RTSP URIs. |
| Prometheus Python client | Planned low-cardinality `/metrics` exposition. |

### Frontend And Tooling

| Technology | Role |
|---|---|
| React 19 + TypeScript 5.9 | Existing operator console. |
| Vite 8 | Frontend build/dev server. |
| Tailwind CSS 4 | Existing UI styling. |
| Docker Compose | Local service and GPU-container orchestration. |
| CMake 3.19+ | C++/CUDA build. |
| pytest / pytest-asyncio | Python unit, contract, and integration tests. |
| CTest | Native protocol, quality, tracking, and lifecycle tests. |
| Ruff + mypy | Python lint and type checks. |

The first RTSP milestone exposes an RTSP URL for VLC/ffplay. Browsers do not
natively play RTSP; WebRTC or HLS playback in the React console is a separate
delivery after the media pipeline is proven reliable. The planned self-hosted
gateway candidate is MediaMTX; it is not an MVP runtime dependency.

## Identity Decision Rules

The approved Friends deployment currently uses:

| Setting | Value |
|---|---:|
| Named recognition threshold | `0.40` |
| Anonymous threshold | `0.78` |
| Video track reconciliation threshold | `0.95` |
| Candidate floor | `0.40` |
| Runner-up margin | `0.05` |

Environment-specific values remain configuration, not constants embedded in
the pipeline. Live defaults must be calibrated independently while preserving
the same rules: named candidates only, threshold, runner-up margin, and
conservative Unknown behavior.

## Source-Verified Reference Map

The repositories were cloned under `/tmp/opencode/ref-*`; their READMEs,
implementation source, exact checkouts, and repository licenses were inspected.

| Reference | Checkout / license | What Mvision Uses | What Mvision Does Not Copy |
|---|---|---|---|
| [Osprey](https://github.com/Ocel-Labs/Osprey) | `b1d81e870ebc9203522c3b60bb5e42fe1098cdea`, Apache-2.0 | Source factory/slot lifecycle, locking discipline, reconnect/readiness and per-stream output topology. | URI exposure, hosted exporter/model hub, full two-container/dynamic-multi-stream topology, teardown without local leak proof. |
| [wjli699 phase3-reid](https://github.com/wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline/tree/feat/phase3-reid) | `001500fabc2784f1e2754cf6d45de37173f51aac`, no repository LICENSE found (`ORACLE_ONLY`) | PGIE-tracker-SGIE ordering, embedding coverage/norm diagnostics, immutable track assignment, DONTWAIT/HWM semantics. | Source code, unverified SGIE config values, first-embedding global person gallery. |
| [Ha-Meem](https://github.com/iam-ajmunna/ha_meem_ai_surveillance) | `00081489369bb6bd150f47f04aa8d92b081af7ad`, no repository LICENSE found (`ORACLE_ONLY`) | Time/quality-weighted evidence, percentile calibration, track expiry and cooldown concepts. | Source code, camera-specific thresholds, Python FAISS/OpenCV hot-path work. |
| [Limitless Surveillance](https://github.com/Limitless-Blue/AI_Enhanced_Surveillance_System) | `48058b6dae1ef87fb4edd16db54926447f9621af`, Apache-2.0 | Camera start/stop contract, review/cooldown ideas, initial size/sharpness/confidence metric candidates. | `cv2.VideoCapture` lifecycle, Redis/Celery/Mongo stack, unverified DeepSORT embedding averaging. |
| [Abdirayimov](https://github.com/Abdirayimov/multi-stream-face-recognition) | `fc885546f2c56de5e989dac38c39b97ca7d2ad31`, MIT | C++ batching/evidence concepts, backpressure concerns, absolute threshold plus top-2 margin. | Per-frame ProbeChain, FAISS gallery, incomplete confirmation and source teardown without proven mux-pad release. |
| [NVIDIA RTSP sample](https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/tree/master/apps/deepstream-rtsp-in-rtsp-out) | `8ad0349ed7a496fae35ebb21c350641727070b89`, Apache-2.0 | DeepStream 9 H.264/RTP/GstRtspServer skeleton, RTSP timestamp guidance, flush/request-pad release pattern. | PyDS production engine and sample-level lifecycle/identity behavior. |

Every adapted pattern must retain URL, checkout, license classification, local
changes, and a test reference in `docs/implementation/live-source-attribution.md`.

## Free And Self-Hosted Boundary

No paid SaaS or hosted service is required by the target architecture.

| Component | Distribution boundary |
|---|---|
| PostgreSQL | Self-hosted, PostgreSQL License. |
| Qdrant | Self-hosted, Apache-2.0. |
| FastAPI | Self-hosted, MIT. |
| GStreamer/GstRtspServer | Self-hosted, LGPL-family plus plugin-specific review. |
| Prometheus | Optional self-hosted metrics collector, Apache-2.0. |
| MediaMTX | Future self-hosted browser gateway, MIT; not required by MVP. |
| Existing MinIO | Community server is AGPLv3; pin and legal-review the validated image or separately validate a checksum-preserving migration to Apache-2.0 SeaweedFS. |
| DeepStream/CUDA/TensorRT | Existing NVIDIA runtime, no managed-service fee, NVIDIA license/EULA and NVIDIA GPU required; not fully open source. |
| Detector/recognizer weights | Provenance and commercial distribution approval remain a separate release gate. |

`latest` container tags are not accepted for a release. Existing persistent
object data is not destructively migrated as part of the first live milestone.

Primary SDK references:

- [DeepStream 9 `nvurisrcbin`](https://docs.nvidia.com/metropolis/deepstream/9.0/text/DS_plugin_gst-nvurisrcbin.html)
- [DeepStream `nvinfer` tensor metadata](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvinfer.html)
- [DeepStream NTP timestamps](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_NTP_Timestamp.html)
- [GStreamer project](https://github.com/GStreamer/gstreamer)

## Repository Layout

```text
Mvision/
├── backend/
│   ├── app/                         FastAPI services and infrastructure
│   ├── pipeline/                    C++17/CUDA/DeepStream workers
│   ├── alembic/                     additive PostgreSQL migrations
│   ├── models/engines/              TensorRT engines
│   └── tests/                       Python tests
├── configs/                         nvinfer, preprocess, and NvDCF configs
├── frontend/                        React operator console
├── architecture/                    research/reference architecture notes
├── docs/superpowers/specs/          approved design records
├── docs/superpowers/plans/          executable implementation plans
├── docker-compose.sprint01.yml      main local stack
└── docker-compose.friends.yml       isolated Friends validation stack
```

## Build And Verification

Build native targets:

```bash
cmake -S backend/pipeline -B build/pipeline
cmake --build build/pipeline -j"$(nproc)"
```

Run native tests directly when the build directory has ownership restrictions:

```bash
./build/pipeline/test_protocol
./build/pipeline/test_video_protocol
./build/pipeline/test_video_aggregation
./build/pipeline/test_face_alignment
LD_LIBRARY_PATH=build/pipeline ./build/pipeline/test_yolo_face_parser
```

Run Python checks from `backend/`:

```bash
pytest tests/unit tests/contract -q
ruff check app tests
mypy app
```

Start the current stack without deleting volumes:

```bash
docker compose -f docker-compose.sprint01.yml up -d --build
```

Never use `docker compose down -v` for routine development because PostgreSQL,
Qdrant, and MinIO contain persistent recognition data.

## Design Documents

- `docs/superpowers/specs/2026-07-21-single-camera-livestream-design.md`
- `docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md`
- `docs/superpowers/plans/2026-07-21-single-camera-livestream.md`
- `docs/superpowers/specs/2026-07-20-phase2-video-backend-design.md`
