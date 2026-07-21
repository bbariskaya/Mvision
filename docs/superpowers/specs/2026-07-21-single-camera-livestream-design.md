# Tek Kamera Livestream Tasarimi

## Durum

Kullanici 2026-07-21 tarihinde Phase 2'nin tamamlandigini ve sonraki urun
hareketinin livestream oldugunu belirledi. Bu belge ilk teslim edilebilir
Phase 3 milestone'unu tanimlar: tek aktif RTSP kamera, guvenilir lifecycle,
yuz tanima, durable detection event'leri, health/metrics ve annotate RTSP
cikisi.

Bu belge implementation source'u degildir. Mevcut davranis ile hedef davranisi
ayirir. Implementation adimlari
`docs/superpowers/plans/2026-07-21-single-camera-livestream.md` dosyasindadir.
Required OpenTelemetry/LGTM behavior is specified in
`docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md`.

## Karar Ozeti

- Ilk milestone tam olarak bir aktif RTSP kamerayi destekler.
- Kamera basina bir Python supervisor ve bir native C++ live worker process'i
  kullanilir.
- Python control plane; API, durable command/state, Qdrant identity karari,
  event persistence, snapshot storage ve metrics sahibidir.
- C++ data plane; RTSP ingest, NVDEC/NVMM, DeepStream inference, tracking,
  quality measurement, bounded temporal evidence, OSD, H.264 encode ve RTSP
  output sahibidir.
- Python ve C++ arasinda stdin/stdout uzerinden duplex, length-prefixed
  MessagePack protocol kullanilir. RTSP URI command-line argument olmaz.
- Pad probe icinde HTTP, PostgreSQL, Qdrant, object storage veya blocking IPC
  cagrisi yapilmaz.
- Known identity ancak named gallery, absolute threshold ve top-2 margin
  kurallarini gecerse atanir. Ambiguous sonuc `Unknown` kalir.
- Bir native track Known olduktan sonra label track bitene kadar immutable'dir.
- Unknown live track ilk milestone'da otomatik global anonymous identity
  olusturmaz. Bu karar transient tracker fragment'lerinin kalici gallery'yi
  kirletmesini engeller ve image API'nin `faceId` contract'ini degistirmez.
- Ilk izlenebilir medya cikisi RTSP'dir. Browser playback sonraki packet'ta
  self-hosted MediaMTX/WebRTC veya HLS ile eklenir.
- Redis, Celery, Kafka, hosted alert servisi ve paid SaaS eklenmez.

## Scope

### Hedefler

1. Encrypted RTSP camera registration ve sanitized query contract'i.
2. Idempotent start/stop/delete ve durable desired state.
3. Worker lease, crash recovery ve stale-worker fencing.
4. `nvurisrcbin` reconnect plus frame watchdog pipeline rebuild.
5. Existing YOLOv8-Face, NvDCF, GPU alignment ve ArcFace embedding uzayini
   koruma.
6. Quality-gated, time-spaced, bounded track evidence.
7. Existing Friends named-gallery voting semantigini live track'e uygulama.
8. Known/Unknown event deduplication ve cooldown.
9. Accepted aligned face snapshot'ini private object storage'da saklama.
10. Bbox, label, cosine score, detector score ve bes landmark OSD.
11. H.264 annotate RTSP output.
12. Health, reconnect, queue, inference ve event metrikleri.
13. Fault injection, repeated teardown ve uzun sureli soak acceptance.

### Ilk Milestone Non-Goals

- Ayni anda birden fazla aktif kamera.
- Runtime dynamic `add_source` / `remove_source` batched pipeline.
- Cross-camera person/body ReID.
- Browser-native player.
- Zone editor veya rule engine.
- Telegram, SMTP, ntfy veya hosted webhook delivery.
- Public internet deployment veya yeni auth platformu.
- Yeni detector/recognizer modeline gecis.
- Existing image/video endpointlerini veya identity schema'sini yeniden yazma.
- Automatic persistent anonymous identity creation from live tracks.

Bu maddeler urun disi degildir. Tek-kamera reliability milestone'undan sonra
ayri acceptance gate'leriyle planlanir.

## Mevcut Gercek

Current uploaded-video native graph:

```text
file
  -> uridecodebin
  -> nvvideoconvert (NVMM)
  -> nvstreammux
  -> nvinfer PGIE / YOLOv8-Face
  -> nvtracker / NvDCF
  -> nvdspreprocess / GPU five-point alignment
  -> nvinfer SGIE / ArcFace R50
  -> result probe
  -> fakesink
```

Current video worker:

- Native process command-line arguments ile baslatilir.
- Native protocol yalniz native -> Python event akisidir.
- Track'ler EOS'ta finalize edilir.
- Python process tracklet reconciliation ve identity voting yapar.
- Pipeline `fakesink` ile sonlanir; live output yoktur.

Live milestone bu davranisi mutate edip file/video semantigini bozmaz. Ayrica
`live_*` protocol, pipeline ve supervisor dosyalari eklenir; ortak, kanitlanmis
detector/alignment/parser kutuphaneleri reuse edilir.

## Runtime ve Model Contract

Installed runtime baseline:

| Bilesen | Deger |
|---|---|
| GPU | 3x Quadro RTX 8000 48 GB |
| Driver | `580.105.08` |
| CUDA | `13.0` |
| TensorRT | `10.16` |
| DeepStream | `9.0.0` |
| GStreamer | `1.24.2` |
| Python | `3.12` |
| Detector | YOLOv8-Face, bbox + 5 landmarks |
| Recognizer | ArcFace R50, finite normalized 512-D |

Live config current video config'lerini kanitsiz degistirmez. Ozellikle su
upstream ayarlar dogrudan kopyalanmaz:

- SGIE `network-type=100`.
- `operate-on-gie-id` kaldirma.
- `secondary-reinfer-interval=1`.
- NvDCF `visualTrackerType=0`.

Her degisiklik once A/B reproducer ile embedding coverage, norm, tracker ID
continuity, hang/crash ve FPS/latency etkisi uzerinden kanitlanir.

## Ust Seviye Mimari

```text
                         CONTROL PLANE

Client
  |
  v
+--------------------------- FastAPI ----------------------------+
| camera API | event API/WS | health | Prometheus metrics         |
+-------+-------------+---------------+----------------------------+
        |             |               |
        v             v               v
  PostgreSQL       Qdrant       private object storage
  camera/run/      named        aligned event snapshots
  event truth      gallery
        |
        | desired state + lease
        v
+--------------------- Python live supervisor --------------------+
| decrypt URI only for start | native process | Qdrant voting     |
| persist state/event        | cooldown       | bounded WS fanout |
+-----------------------------+------------------------------------+
                              | duplex framed MessagePack
                              v
                         GPU DATA PLANE

+----------------------- C++ live worker --------------------------+
| RTSP/NVDEC -> detect -> track -> quality -> align -> ArcFace     |
|               |                                  |               |
|               +-> bounded TrackEvidence --------+               |
|               |                                                  |
| IdentityAssignment -> label map -> OSD -> NVENC -> RTSP output   |
+------------------------------------------------------------------+
```

## Process Topology

Ilk milestone'da bir worker process bir camera run'a aittir:

```text
api container                         live-worker-0 container
--------------------------            ------------------------------
POST start -> desired=running         poll/claim desired camera
                                      create run + lease
                                      decrypt URI
                                      spawn mvision_live_worker
                                      send Start command over stdin
                                      consume stdout events
                                      send IdentityAssignment/Stop
                                      persist runtime/event state

native crash -----------------------> bounded retry + generation++
lease lost -------------------------> stale supervisor stops child
desired=stopped --------------------> Stop -> GST_STATE_NULL -> STOPPED
```

API process native child process sahibi olmaz. Bu sayede API restart'i aktif
worker lease ve desired state'i kaybetmez. `live-worker-0` current video worker
orchestration pattern'ini reuse eder fakat perpetual process semantigi tasir.

## Kamera ve Run State Modeli

### Desired State

`live_camera.desired_state` yalniz:

- `stopped`
- `running`

Start/stop endpoint'i durable intent yazar. Runtime state uydurmaz.

### Runtime State

`live_camera_run.runtime_state`:

```text
                  Start command
STOPPED --------------------------------> STARTING
   ^                                          |
   |                                          | first valid frame
   |                                          v
   |                                       ACTIVE
   |                                          |
   |                                          | no frame watchdog
   |                                          v
   |                                    RECONNECTING
   |                                          |
   |                     valid frame ---------+
   |                                          |
   |                                          | attempts exhausted/fatal
   |                                          v
   |                                        FAILED
   |                                          |
   +---------- STOPPING <---------------------+
                  ^
                  |
       stop from STARTING/ACTIVE/RECONNECTING/FAILED
```

Rules:

- Runtime state yalniz native state event'i veya supervisor lifecycle sonucu
  degisir.
- Her start attempt yeni UUIDv7 `run_id` ve monoton `generation` alir.
- Her protocol event `camera_id`, `run_id`, `generation` tasir.
- Eski generation event/assignment'i reddedilir.
- Stop idempotent'tir; `STOPPED` kamerayi stop etmek success dondurur.
- Ikinci camera start istegi `409 LIVE_CAMERA_LIMIT_REACHED` dondurur.
- Tek aktif limit database partial unique index'iyle race-safe enforced edilir.

## Durable Data Model

### `live_camera`

| Alan | Contract |
|---|---|
| `camera_id` | UUIDv7 primary key |
| `name` | operator-visible unique display name |
| `uri_ciphertext` | encrypted RTSP URI, never returned |
| `uri_fingerprint` | keyed HMAC for duplicate detection, not reversible |
| `desired_state` | `stopped` or `running` |
| `is_active` | soft-delete flag |
| `created_at` / `updated_at` / `deleted_at` | audit timestamps |

### `live_camera_run`

| Alan | Contract |
|---|---|
| `run_id` | UUIDv7 primary key |
| `camera_id` | active camera foreign key |
| `generation` | monoton per-camera generation |
| `runtime_state` | lifecycle state |
| `worker_id` / `lease_token` / `lease_expires_at` | fenced ownership |
| `started_at` / `first_frame_at` / `last_frame_at` | health timestamps |
| `stopped_at` | terminal timestamp |
| `reconnect_count` | source recovery count |
| `output_path` | sanitized RTSP mount path only |
| `error_code` / `sanitized_error` | no URI/secret/raw exception |
| `metrics` | bounded latest runtime counters JSONB |

### `live_detection_event`

| Alan | Contract |
|---|---|
| `event_id` | UUIDv7 primary key |
| `camera_id` / `run_id` | source and generation |
| `native_track_id` | run-local tracker ID |
| `event_type` | `known` or `unknown` |
| `face_id` | known match FK; null for Unknown |
| `name_snapshot` | immutable known name; null for Unknown |
| `identity_version_snapshot` | known identity version; null for Unknown |
| `match_score` / `nearest_known_score` | decision evidence |
| `detector_confidence` | representative observation score |
| `first_seen_at` / `last_seen_at` / `occurred_at` | UTC timestamps |
| `bounding_box` / `landmarks` | source-coordinate representative geometry |
| `quality` | metrics, rejection counts and selected sample metadata |
| `snapshot_bucket` / `snapshot_object_key` | private aligned evidence location |
| `created_at` | durable insertion timestamp |

Event uniqueness key:

```text
(run_id, native_track_id, event_type)
```

Known track immutable oldugu icin track basina bir Known event yeterlidir.
Unknown event ancak track expiry/minimum dwell sonrasinda ve cooldown policy
izin verirse persist edilir.

## API Contract

| Method | Endpoint | Davranis |
|---|---|---|
| `POST` | `/api/v1/cameras` | Encrypted URI ile camera olusturur. |
| `GET` | `/api/v1/cameras` | Sanitized records ve latest runtime state. |
| `GET` | `/api/v1/cameras/{cameraId}` | Sanitized camera/run health. |
| `POST` | `/api/v1/cameras/{cameraId}/start` | Desired state `running`. |
| `POST` | `/api/v1/cameras/{cameraId}/stop` | Desired state `stopped`. |
| `DELETE` | `/api/v1/cameras/{cameraId}` | Stop + soft delete. |
| `GET` | `/api/v1/cameras/{cameraId}/events` | Cursor-paginated durable events. |
| `GET` | `/api/v1/cameras/{cameraId}/events/{eventId}/snapshot` | Private snapshot stream. |
| `GET` | `/api/v1/cameras/{cameraId}/health` | Current run health and counters. |
| `WS` | `/api/v1/live/events` | Best-effort notification fanout. |
| `GET` | `/metrics` | Prometheus text exposition. |

`POST /api/v1/cameras` input:

```json
{
  "name": "north-entrance",
  "rtspUri": "rtsp://user:password@10.0.0.12:554/stream1"
}
```

Response URI'yi geri dondurmez:

```json
{
  "cameraId": "uuid",
  "name": "north-entrance",
  "desiredState": "stopped",
  "runtimeState": "STOPPED",
  "outputUrl": null,
  "createdAt": "2026-07-21T00:00:00Z"
}
```

Stable errors:

- `CAMERA_NOT_FOUND`
- `CAMERA_NAME_CONFLICT`
- `CAMERA_URI_INVALID`
- `LIVE_URI_ENCRYPTION_UNAVAILABLE`
- `LIVE_CAMERA_LIMIT_REACHED`
- `LIVE_CAMERA_ALREADY_DELETED`
- `LIVE_WORKER_UNAVAILABLE`
- `LIVE_PIPELINE_ERROR`
- `LIVE_SOURCE_UNREACHABLE`
- `LIVE_OUTPUT_UNAVAILABLE`
- `LIVE_EVENT_NOT_FOUND`
- `LIVE_SNAPSHOT_NOT_AVAILABLE`

## RTSP Credential Security

- `rtspUri` write-only input'tur.
- Scheme yalniz `rtsp` veya `rtsps` olabilir.
- URI length, host ve port parse edilir; userinfo bulunabilir fakat loglanmaz.
- Encryption `LIVE_URI_ENCRYPTION_KEYS` ile authenticated encryption kullanir.
- Ciphertext PostgreSQL'de saklanir; plaintext yalniz worker claim sonrasinda
  memory'de kisa sure bulunur.
- URI native process argv veya environment'ina yazilmaz; framed Start command
  ile stdin'den iletilir.
- `ps`, Docker inspect ve process logs URI'yi gostermez.
- Redactor URI userinfo, query ve camera host detayini error/log'dan siler.
- Prometheus label'larinda camera name, URI, host, face name veya face ID yoktur.
- API trusted/private network disina auth olmadan publish edilmez.
- Container egress camera network, PostgreSQL, Qdrant ve object storage ile
  sinirlandirilir; arbitrary public URI SSRF release gate'idir.

Key rotation bu milestone'un runtime endpoint'i degildir. Rotation runbook'u;
yeni key ile decrypt/re-encrypt transaction'i ve rollback backup'i gerektirir.

## Duplex Native Protocol

Framing:

```text
4-byte big-endian payload length | MessagePack map
```

Global fields:

```text
protocol_version = 1
message_type
camera_id
run_id
generation
sequence
```

Python -> native commands:

- `start`: plaintext URI, GPU ID, config paths, output mount/UDP port and
  bounded operational settings.
- `identity_assignment`: tracker ID, `known|unknown`, display name, face ID,
  match score and decision sequence.
- `stop`: reason and bounded shutdown deadline.

Native -> Python events:

- `hello`: protocol/build/runtime identity.
- `state`: lifecycle transition and sanitized reason.
- `output_ready`: mount path and codec/caps.
- `track_evidence`: bounded observations and normalized embeddings.
- `track_expired`: track end signal for Unknown finalization.
- `metrics`: counters and gauges without high-cardinality identity labels.
- `failed`: stable error code and sanitized message.
- `stopped`: terminal counters and clean-shutdown status.

`track_evidence` contains:

```text
tracker_id: uint64
evidence_revision: uint64
first_seen_ns / last_seen_ns: uint64
observations: max 10
  timestamp_ns
  source bbox
  detector confidence
  five source landmarks + confidences when available
  quality metrics + reject mask
  normalized embedding[512]
representative_aligned_jpeg: bounded bytes, only after evidence contract gate
```

Decoder rejects:

- unknown protocol version or message type;
- frame above configured maximum;
- wrong camera/run/generation;
- non-finite values;
- embedding length other than 512;
- embedding norm outside tolerance;
- landmark length other than 10 coordinates;
- out-of-order assignment revision;
- oversized snapshot.

## Native Pipeline

```text
RTSP camera
  |
  v
nvurisrcbin
  | NVDEC / NVMM, latency, drop-on-latency, reconnect
  v
queue -> nvvideoconvert -> nvstreammux(batch-size=1, live-source=1)
  |
  v
nvinfer PGIE / YOLOv8-Face / bbox + 5 landmarks
  |
  v
nvtracker / NvDCF / run-local object_id
  |
  +---- quality metadata and sampling gate
  |
  v
nvdspreprocess / GPU five-point 112x112 alignment
  |
  v
nvinfer SGIE / ArcFace R50 / normalized 512-D
  |
  +---- result probe -> bounded native evidence bank -> writer queue
  |
  v
queue -> OSD label probe -> nvdsosd -> nvvideoconvert
  -> nvv4l2h264enc -> h264parse -> rtph264pay -> udpsink(loopback)
                                                     |
                                                     v
                                              GstRtspServer
                                              /live/<cameraId>
```

The official NVIDIA RTSP sample's local RTP/UDP bridge is used as a skeleton,
not as production lifecycle logic. UDP port is loopback-bound and allocated
from a configured private range. `GstRtspServer` mount is sanitized UUID-based.

OSD branch has a downstream-leaky bounded queue. A slow/no viewer cannot block
decode, inference or event production.

## Reconnect ve Watchdog

Layer 1, `nvurisrcbin` properties:

- `rtsp-reconnect-interval`
- `rtsp-reconnect-attempts`
- `latency`
- `drop-on-latency`

Exact property support and unit installed DeepStream 9 container'da
`gst-inspect-1.0 nvurisrcbin` ile frozen edilir.

Layer 2, frame watchdog:

```text
last frame age <= stale threshold      ACTIVE
last frame age > stale threshold       RECONNECTING
plugin recovery produces valid frame  ACTIVE + reconnect_count
recovery deadline exceeded             controlled pipeline rebuild
rebuild budget exhausted               FAILED
```

Rebuild kurallari:

- Old pipeline once `GST_STATE_NULL`.
- Bus/watch/probe/signal handlers detached.
- Requested mux pad release edilir.
- RTSP server mount ve UDP resources release edilir.
- Queue/writer drain bounded'dir; shutdown frame-rate thread'i bekletmez.
- New generation same run icinde kullanilmaz; full process restart yeni run
  generation olusturur.
- Backoff bounded exponential + jitter'dir.
- Stop command reconnect/backoff sleep'ini interrupt eder.

## Quality ve Evidence Pipeline

Production threshold'lari upstream README'den kopyalanmaz. Ilk asama shadow
mode'dur: her metric collect edilir fakat identity gating yalniz mevcut safe
minimumlarla calisir. Deployment footage percentile'lari incelendikten sonra
quality policy freeze edilir.

Metric/gate set:

| Gate | Baslangic guardrail | Not |
|---|---:|---|
| Detector confidence | config, current parser floor altinda olamaz | Current detector parity korunur. |
| Minimum face side | `60 px` candidate baseline | Limitless'ten calibration adayi. |
| Border clipping | max `10%` candidate | Source-coordinate bbox. |
| Landmark validity | finite, in/near bbox, canonical order | Confidence varsa ayrica collect. |
| Absolute yaw | `45 deg` candidate | Landmark proxy, calibration gerekir. |
| Absolute pitch | `35 deg` candidate | Landmark proxy, calibration gerekir. |
| Absolute roll | `30 deg` candidate | Alignment sanity. |
| Brightness | `35..220` candidate | Aligned crop metric. |
| Sharpness | Laplacian variance `80` candidate | Camera-specific, shadow first. |
| Embedding | exactly 512, finite, norm tolerance | Hard gate. |
| Observation spacing | `200 ms` candidate | Near-duplicate suppression. |
| Evidence capacity | best `10` | Hard memory bound. |
| Minimum evidence | `3` and `0.5 s` candidate | One-frame Known prevention. |

Quality score identity score degildir. Evidence ranking su bilgileri kullanir:

```text
detector confidence
x normalized face area
x pose/landmark sanity weight
x sharpness/exposure weight
x viewpoint diversity bonus
```

Native bank:

- Track key `(run_id, tracker_id)`.
- Max 10 accepted observations.
- New observation too close in time/viewpoint ise ancak daha iyi quality ile
  eski observation'i replace eder.
- Heap/vector allocation capacity track create aninda bounded olur.
- Expired track state, assignment map ve snapshots temizlenir.
- Probe only computes/copies compact metadata and attempts non-blocking queue.

## Identity Decision

Existing `VideoIdentityVotingService` semantigi korunur ve live input adapter
ile reuse edilir:

1. Her accepted observation embedding'i icin Qdrant candidates al.
2. Candidate identity'yi PostgreSQL active lifecycle ile dogrula.
3. Yalniz `known` lifecycle candidate'larini vote'a al.
4. Her identity icin en iyi sample'i bir observation'da bir vote say.
5. Candidate floor altini reject et.
6. Weighted mean ile winner/runner sirala.
7. Winner'in en az bir score'u absolute recognition threshold'u gecmeli.
8. Winner mean - runner mean en az configured margin olmali.
9. Kosullar saglanmazsa nearest known score audit icin korunur fakat sonuc
   Unknown olur.
10. Known karari native worker'a revision'li assignment olarak gonderilir.

Friends deployment values:

```text
recognition threshold = 0.40
candidate floor       = 0.40
top-2 margin          = 0.05
```

Bu sayilar global default degildir. Environment/model/preprocess version ile
snapshot edilir ve live calibration sonucu olmadan baska deployment'a
`production calibrated` diye tasinmaz.

Track immutability:

- `Pending -> Known` allowed.
- `Pending -> Unknown` display allowed; later strong evidence gelirse Known
  olabilir, durable Unknown event henuz yazilmaz.
- `Known(A) -> Known(B)` forbidden.
- `Known -> Unknown` forbidden.
- Known identity DB'de inactive olursa current track label degismez; sonraki
  yeni track candidate validation'da reddedilir.

## Event ve Snapshot Policy

Known event:

- First accepted Known assignment'ta bir kez persist.
- Same face/camera cooldown penceresinde yeni tracker fragment'i olursa event
  suppress edilebilir; suppression counter artar.
- Durable row commit olmadan WebSocket notification success sayilmaz.

Unknown event:

- Minimum dwell/evidence kosulu saglanir.
- Track expiry veya configured stable Unknown delay beklenir.
- Camera-level cooldown ile event storm engellenir.
- `face_id=null`, `name=null` olur.

Snapshot:

- Full source frame degil, identity kararinda kullanilan canonical aligned face
  evidence olur.
- Gercek format, dimensions, media type ve bytes runtime test edilir.
- GPU-native encode yolu kanitlanmadan original frame veya CPU PIL/OpenCV
  fallback kullanilmaz.
- Object key technical UUID segmentleri kullanir:
  `live/{cameraId}/{eventId}/aligned`.
- Bucket private'dir; API stream eder veya short-lived server-side retrieval
  yapar. Public/long-lived URL yoktur.

## Backpressure

| Veri | Queue dolunca policy |
|---|---|
| Metrics | Old pending sample replace edilir. |
| Evidence same track | Newer/higher-quality revision ile coalesce edilir. |
| State transition | Drop edilmez; enqueue olmazsa worker degraded/fail olur. |
| Failure/stopped | Reserved control capacity; drop edilmez. |
| Identity assignment | Latest revision per tracker coalesce edilir. |
| WebSocket message | Subscriber queue oldest drop; durable row kalir. |
| OSD/video | Downstream-leaky; viewer inference'i block etmez. |

Queue depth, drops, coalesces ve writer lag metrics olarak expose edilir.

## Timestamp Contract

- `buf_pts` pipeline-relative ordering icin kullanilir.
- RTSP NTP/RTCP sender report support installed source ile dogrulanir.
- Absolute `occurred_at` tercih sirasi:
  1. valid source/NTP timestamp;
  2. supervisor monotonic-to-UTC anchor;
  3. server receive UTC with `timestamp_source=server`.
- Timestamp geriye giderse ordering monoton sequence ile korunur ve
  `timestamp_regression_total` artar.
- Future multi-camera correlation yalniz NTP health kanitlandiktan sonra acilir.

## Observability

Prometheus health/metric contracts below remain required. End-to-end logs,
traces, Collector routing, Loki, Tempo, Grafana provisioning, retention,
correlation, alerts, and observability acceptance are additionally governed by
`docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md`.

Health response:

```text
cameraId, runId, generation
desiredState, runtimeState
firstFrameAt, lastFrameAt, frameAgeSeconds
sourceFps, processedFps, outputFps
reconnectCount, lastReconnectAt
activeTracks, pendingEvidence
nativeQueueDepth, nativeDroppedEvidence
pythonQueueDepth, websocketDroppedMessages
lastErrorCode
outputReady, outputUrl
```

Prometheus metric names:

```text
mvision_live_worker_up
mvision_live_runtime_state
mvision_live_frames_total
mvision_live_frame_age_seconds
mvision_live_reconnects_total
mvision_live_active_tracks
mvision_live_embeddings_total
mvision_live_missing_embeddings_total
mvision_live_quality_rejections_total{reason}
mvision_live_protocol_queue_depth
mvision_live_protocol_dropped_total{type}
mvision_live_identity_decisions_total{outcome}
mvision_live_events_total{type}
mvision_live_event_suppressions_total{reason}
mvision_live_output_frames_total
mvision_live_websocket_dropped_total
```

Allowed labels low-cardinality enum'lardir. `camera_id`, `track_id`, `face_id`,
name, URI veya host metric label'i olmaz.

Structured logs `camera_id`, `run_id`, generation ve stable error code
tasiyabilir; RTSP URI, name/PII, embedding, raw snapshot veya query response
tasimaz.

## Free/Self-Hosted Stack ve License Gate

| Bilesen | Kullanimi | License/constraint | Karar |
|---|---|---|---|
| PostgreSQL | Durable truth/leases/events | PostgreSQL License | ADOPT |
| Qdrant | Named vector gallery | Apache-2.0 | ADOPT |
| FastAPI | API/WS | MIT | ADOPT |
| MessagePack | Native protocol | Boost/Python package terms | ADOPT |
| Prometheus client/server | Metrics | Apache-2.0 | ADOPT, server optional |
| GStreamer/GstRtspServer | Media plumbing | LGPL-family, plugin-specific review | ADOPT with notice review |
| MediaMTX | Future browser gateway | MIT | FUTURE, not MVP runtime |
| SeaweedFS | Possible S3-compatible storage | Apache-2.0 | EVALUATE migration |
| MinIO community image | Existing object storage | Current repository AGPLv3; distribution/support posture changed | PIN_AND_REVIEW |
| DeepStream 9 | GPU analytics | NVIDIA SDK EULA, NVIDIA GPU required | EXISTING_REQUIRED |
| CUDA/TensorRT binaries | GPU execution | NVIDIA license terms; OSS portions differ | EXISTING_REQUIRED |
| Model artifacts | Detector/recognizer | Weight provenance separate from source license | RELEASE_BLOCKED_REVIEW |

No paid component is required. `free/self-hosted` does not mean every NVIDIA
binary is open source. Legal approval and notice/distribution obligations are
release gates, not implementation assumptions.

Current persistent MinIO data is not destructively migrated during this
milestone. Before production packaging choose one:

1. Pin an approved community MinIO version and accept/fulfil AGPL obligations.
2. Validate the existing S3 adapter against Apache-2.0 SeaweedFS, migrate with
   checksum/reconciliation tooling and retain rollback.

`latest` image tags are forbidden for the release compose.

## Upstream Source Audit

| Reference | Commit | License | Adopt/Adapt | Do not copy |
|---|---|---|---|---|
| `Abdirayimov/multi-stream-face-recognition` | `fc885546f2c56de5e989dac38c39b97ca7d2ad31` | MIT | C++ batching concepts, threshold + top-2 margin | Per-frame ProbeChain, incomplete confirmation, teardown without proven request-pad release |
| `Limitless-Blue/AI_Enhanced_Surveillance_System` | `48058b6dae1ef87fb4edd16db54926447f9621af` | Apache-2.0 | Initial quality metrics and cooldown/review concepts | `cv2.VideoCapture` lifecycle, mixed Python hot path, unverified DeepSORT averaging |
| `wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline` `feat/phase3-reid` | `001500fabc2784f1e2754cf6d45de37173f51aac` | no repository LICENSE found | SGIE diagnostics, coverage/norm counters, non-blocking HWM pattern | Source copy, first-embedding global ReID, config values without A/B proof |
| `Ocel-Labs/Osprey` | `b1d81e870ebc9203522c3b60bb5e42fe1098cdea` | Apache-2.0 | Source factory, locks, reusable stream states, reconnect/health concepts | URI exposure, full topology, teardown behavior without local leak test |
| `iam-ajmunna/ha_meem_ai_surveillance` | `00081489369bb6bd150f47f04aa8d92b081af7ad` | no repository LICENSE found | Temporal quality aggregation, percentile calibration, expiry | Source copy, camera-specific thresholds, matching/snapshot work in probe path |
| `NVIDIA-AI-IOT/deepstream_python_apps` | `8ad0349ed7a496fae35ebb21c350641727070b89` | Apache-2.0 | Official RTSP output skeleton, `flush_stop` + request-pad release pattern | Python/PyDS production engine, sample-level lifecycle |

Repos source inspection icin `/tmp/opencode/ref-*` altina clone edilmistir.
No-license repos `ORACLE_ONLY` kalir. Her adapted source/pattern implementation
commit'inde URL, commit ve license attribution decision log'a yazilir.

## Failure Matrix

| Failure | Beklenen davranis |
|---|---|
| Camera DNS/connect fail | STARTING/RECONNECTING, bounded retry, sanitized error |
| RTSP packet loss/stall | Plugin reconnect, watchdog, no API blocking |
| Camera credentials wrong | retries exhausted -> FAILED, secret not logged |
| Native crash | run failed, lease-safe restart with new generation |
| API restart | active worker continues; desired/runtime query DB'den gelir |
| Supervisor restart | expired lease reclaimed; stale child fenced/stopped |
| PostgreSQL unavailable | no false durable event; bounded queue then degraded/fail |
| Qdrant unavailable | track remains Unknown/Pending; no guessed Known |
| Object storage unavailable | event records snapshot failure explicitly; no fake key |
| WebSocket consumer slow | subscriber messages dropped, durable event preserved |
| RTSP viewer slow/disconnect | leaky output queue, inference unaffected |
| Embedding missing/non-finite | reject/counter; no identity query |
| OSD assignment stale | generation/revision rejection |
| Stop during reconnect | backoff interrupted, clean GST_STATE_NULL |
| Repeated start/stop | no mux pad, mount, port, thread or GPU memory leak |

## Acceptance

### Contract

- Camera URI never appears in API response, process argv, logs or metrics.
- Start/stop/delete are idempotent.
- Concurrent second start returns `409` and DB invariant remains valid.
- Stale lease/generation cannot persist state or identity assignment.
- Protocol rejects malformed/oversized/non-finite payloads.

### Native/GPU

- Real RTSP H.264 input reaches NVDEC -> PGIE -> NvDCF -> GPU alignment ->
  SGIE.
- Bbox/landmark coordinates are source-space correct.
- At least expected live objects receive finite 512-D normalized embeddings;
  coverage and missing count are reported.
- Known identity satisfies named-only threshold + margin.
- Ambiguous identity remains Unknown.
- OSD includes required fields and RTSP output is playable with `ffprobe` and
  `ffplay`/VLC.
- Slow/no output viewer does not stop input/inference counters.

### Resilience

- Disconnect/reconnect camera source and observe state cycle.
- Stop during reconnect completes inside deadline.
- Kill native child and verify durable failed/restarted run generation.
- Restart API without losing active worker state.
- Repeat start/stop at least 50 cycles without increasing thread, fd, request
  pad, RTSP mount or GPU-memory baseline beyond accepted tolerance.
- Soak real camera for 24 hours with bounded RSS/GPU memory/queue depth and no
  unhandled crash before production claim.

### Storage

- PostgreSQL test schema uses `_test` database.
- Qdrant test collection and object-storage test buckets cannot resolve to
  production names.
- Known/Unknown event rows and aligned snapshot references survive restart.
- Snapshot bytes decode to exact accepted aligned dimensions/media type.
- No destructive volume reset is used.

## Rollout

1. Compatibility spikes and legal/storage gates.
2. Protocol and pure state/quality units.
3. Native local RTSP fixture smoke without persistence.
4. Python supervisor + durable camera/run state.
5. Identity voting + event persistence + snapshot.
6. OSD and annotate RTSP output.
7. Metrics and fault injection.
8. Shadow quality calibration on deployment footage.
9. Single-camera soak and acceptance.
10. Feature flag `LIVE_ENABLED=true` only after gates pass.

Rollback sets desired state stopped, disables `LIVE_ENABLED`, stops the live
worker and leaves additive database records intact. Existing image/video
services remain available.

## Future Scale-Out

### Dynamic Multi-Camera

After single-camera acceptance:

```text
camera registry
  -> scheduler/admission control
  -> one DeepStream process per GPU
  -> dynamic nvurisrcbin slots
  -> nvstreammux batch N
  -> nvstreamdemux output per camera
```

Required new gates: request-pad release, slot generation fencing, per-source
watchdog, heterogeneous FPS fairness, batch timeout calibration, one-camera
failure isolation and GPU memory admission.

### Browser Playback

Keep native RTSP output stable and place self-hosted MediaMTX at the edge:

```text
Mvision RTSP -> MediaMTX -> WebRTC (preferred low latency) / HLS fallback
```

Browser transport does not enter inference process. Authentication, TURN,
retention and network exposure receive a separate security design.

### Cross-Camera ReID

Face identity and body ReID are separate evidence spaces:

```text
camera-local tracker IDs
  -> face Known assignments where visible
  -> separate body ReID model/gallery
  -> timestamp/topology-aware association
  -> global person journey
```

No face embedding is relabeled as a body embedding. NTP health, camera topology,
cannot-link constraints and a separately licensed/calibrated person-ReID model
are mandatory before this phase.

## Superseded Document

The previous Phase 3 reference note was removed after its verified findings
were migrated here. It recommended Redis/Celery and dynamic multi-camera before
proving single-camera reliability, treated no-license source as directly
adaptable, and contained unverified implementation claims. This design and its
implementation plan are the canonical Phase 3 documents.
