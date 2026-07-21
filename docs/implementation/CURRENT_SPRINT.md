# Sprint 03 - Tek Kamera RTSP Canli Yayin

## Yetki ve Durum

Kullanici 2026-07-21 tarihinde Phase 2'nin tamamlandigini ve sonraki urun
hareketinin livestream oldugunu acikca belirledi. Bu sprint Phase 3 canli akis
calismasini yetkilendirir. Phase 1 ve Phase 2 belgelerindeki RTSP non-goal
ifadeleri yalniz kendi tamamlanmis fazlarinin siniridir; bu sprinti engellemez.

Packet 0 belgeleri, Packet 1 compatibility/control-plane contracts, Packet 2
protocol/native track state ve Packet 3 Task 7 RTSP ingest/inference zinciri
tamamlanmistir. Reconnect, output pipeline, supervisor ve required self-hosted
OpenTelemetry/Prometheus/Loki/Tempo/Grafana source'u henuz yazilmamistir.

## Objective

Mevcut YOLOv8-Face, NvDCF, GPU five-point alignment, ArcFace R50, Qdrant
gallery ve track-level identity voting zincirini, tek aktif RTSP kamera icin
uzun sure calisabilen bir DeepStream 9 pipeline'ina tasimak. Ilk teslim;
guvenli kamera lifecycle'i, reconnect, quality-gated temporal evidence,
durable detection events, health/metrics ve annotate edilmis RTSP cikisi
uretir.

## Approved Architecture

- Design:
  `docs/superpowers/specs/2026-07-21-single-camera-livestream-design.md`
- Execution plan:
  `docs/superpowers/plans/2026-07-21-single-camera-livestream.md`
- Required observability design:
  `docs/superpowers/specs/2026-07-21-opentelemetry-observability-design.md`
- Repository overview: `README.md`

## Packet 0 - Source-Verified Design and Plan

- [x] Mevcut image/video source, config, test ve runtime envanteri incelendi.
- [x] Alti upstream reference gecici dizine clone edilerek implementation
  source'u, commit ve license bilgisi incelendi.
- [x] DeepStream 9 `nvurisrcbin`, reconnect, tensor metadata, NTP ve official
  RTSP output davranislari current docs/source ile kontrol edildi.
- [x] Source-verified design document'i tamamla.
- [x] Exact dosya, interface, RED/GREEN test ve acceptance adimlari olan
  implementation planini tamamla.
- [x] README ile design/plan arasindaki status, link ve terminology uyumunu
  dogrula.

## Packet 1 - Compatibility and Contracts

- [x] Installed DeepStream 9/GStreamer/GstRtspServer factory ve property
  capability reproducer'i.
- [x] RTSP URI validation, Fernet encryption/rotation, HMAC fingerprint ve log
  redaction.
- [x] Additive `live_camera`, `live_camera_run` ve `live_detection_event`
  migration/model/repository contracts.
- [x] Write-only URI camera API, durable desired state, tek aktif kamera limiti
  ve sanitized response contracts.

Model/engine live SGIE compatibility, NvDCF A/B, gercek RTSP reconnect/teardown,
snapshot storage ve output pipeline acceptance sonraki packet'lerde kalir. Bu
gate'lerden biri fail olursa production davranisi uydurulmaz; ilgili packet
`BLOCKED` olarak raporlanir.

## Packet 2 - Protocol and Native Track State

- [x] 4 MiB bounded, network-order framed MessagePack command/event codec.
- [x] Python/C++ parity for Start, IdentityAssignment, Stop and native event
  payloads.
- [x] UUID/generation/revision, finite metric, embedding norm, landmark and
  512 KiB snapshot validation.
- [x] Deterministic shadow quality metrics and hard reject mask.
- [x] Capacity-10 evidence replacement, temporal/view diversity and deterministic
  tie breaks.
- [x] Immutable Known assignment state and stale revision rejection.
- [x] ASan/UBSan 100,000-observation bounded-capacity stress.

## First Milestone Deliverables

- Tek aktif kamera limiti ve durable desired/runtime state.
- RTSP URI credential encryption, write-only API ve log redaction.
- `nvurisrcbin` tabanli NVDEC/NVMM ingest ve iki katmanli reconnect.
- YOLOv8-Face -> NvDCF -> GPU alignment -> ArcFace R50 zinciri.
- Frame-rate probe icinde database/network/storage cagrisi olmayan bounded
  native track evidence bank.
- Duplex framed MessagePack command/event protocol.
- Named-only Qdrant voting, absolute threshold, top-2 margin ve track boyunca
  immutable Known etiketi.
- Quality reject reason'lari, shadow calibration ve bounded best-shot secimi.
- PostgreSQL camera/runtime/detection event kayitlari.
- Private object storage'da accepted aligned face snapshot'i.
- Bbox, label, cosine score, detector score ve bes landmark iceren OSD.
- H.264 annotate RTSP output.
- Health, queue/backpressure ve reconnect metrikleri.
- Fault injection, repeated teardown ve soak acceptance.

## Invariants

- `face_id` global identity anahtaridir; native `track_id` yalniz camera-run
  local hareket kimligidir.
- Ayni native track icinde Known label degismez; ambiguous sonuc Unknown kalir.
- Anonymous gallery adayi named identity'yi baskilayamaz.
- Qdrant adayi PostgreSQL active lifecycle ile dogrulanmadan final kabul
  edilmez.
- Full decoded frame, RGB/BGR frame veya inference tensor'u Python/API
  process'ine tasinmaz.
- Pad probe HTTP, PostgreSQL, Qdrant veya object storage cagirmaz.
- Queue'lar bounded'dir; video output viewer backpressure'i inference'i
  durdurmaz.
- RTSP URI/credential process argument, log, error, metric label veya API
  response'a girmez.
- Mevcut PostgreSQL, Qdrant ve object-storage volume'lari silinmez veya reset
  edilmez.
- Existing image/video endpoint ve identity lifecycle davranisi korunur.

## First Milestone Non-Goals

Bu maddeler yalniz ilk tek-kamera milestone'u icin ertelenmistir:

- Runtime dynamic multi-camera batching.
- Birden fazla aktif kamera.
- Cross-camera body/person ReID.
- Browser-native WebRTC/HLS player.
- Zone/rule engine ve Telegram/e-mail/hosted alert kanallari.
- Redis, Celery, Kafka veya managed event bus.
- Kubernetes, distributed scheduler veya microservice parcasi.
- Model, detector, ArcFace embedding space veya threshold'u kanitsiz degistirme.

## Runtime Inventory

- GPU: 3x Quadro RTX 8000 48 GB.
- Driver: `580.105.08`.
- CUDA: `13.0`.
- TensorRT: `10.16`.
- DeepStream: `9.0.0`.
- GStreamer: `1.24.2`.
- Python: `3.12`.
- Existing detector: YOLOv8-Face with five landmarks.
- Existing recognizer: ArcFace R50, normalized 512-D embedding.
- Existing stores: PostgreSQL, Qdrant and MinIO-compatible object storage.

## Acceptance Commands

Document packet:

```bash
test -f docs/superpowers/specs/2026-07-21-single-camera-livestream-design.md
test -f docs/superpowers/plans/2026-07-21-single-camera-livestream.md
git diff --check
```

Implementation packet commands are defined task-by-task in the execution plan.
No implementation packet receives PASS from unit mocks alone; real RTSP,
DeepStream GPU, PostgreSQL, Qdrant and object-storage evidence is required at
the relevant gates.

## Evidence Classification

- `SOURCE_VERIFIED`: current image/video source, current configs, upstream
  implementations, official DeepStream/GStreamer documentation.
- `RUNTIME_VERIFIED`: installed NVIDIA runtime and completed image/video GPU
  paths recorded by prior packets.
- `NOT_PROVEN`: live reconnect, annotated RTSP output, live snapshots, 24-hour
  soak and multi-camera scale.
- `RELEASE_BLOCKED_LEGAL_REVIEW`: model/weight provenance, NVIDIA EULA release
  obligations and object-storage distribution choice.

## Hard Stops

- Exact installed plugin/property davranisi reproducer ile kanitlanamiyor.
- Live pipeline, aligned evidence veya RTSP output yalniz CPU fallback ile
  calisabiliyor.
- Source teardown request pad/resource leak veya repeated restart crash
  uretiyor.
- SGIE embedding coverage/norm parity existing video pipeline ile korunamiyor.
- RTSP credential redaction/encryption testi fail ediyor.
- Schema degisikligi additive migration ile yapilamiyor.
- Gercek GPU/dependency acceptance calistirilamiyor fakat sonuc PASS diye
  raporlanmak isteniyor.
- Model/engine/system CUDA/driver degisikligi gerekiyor.
- Destructive volume/data islemi gerekiyor.

## Current Evidence

- Friends uploaded-video run: `6665/6665` frames, 122 canonical tracks and
  8934 detections.
- Native video aggregation/protocol, face alignment and detector parser tests
  passed in the previous packet.
- Packet 0 documentation: `PASS`.
- Packet 1 installed runtime contract: `PASS`; required 11 factories, five
  `nvurisrcbin` properties and GstRtspServer are present in the pinned runtime.
- Packet 1 URI security tests: `12 passed`.
- Packet 1 persistence integration tests: `7 passed`; migration
  `7d6f0b3a9c21` upgrade/downgrade/re-upgrade verified against test PostgreSQL.
- Packet 1 camera service/API tests: `12 passed`; camera/video contract set:
  `8 passed`.
- Packet 2 Python protocol/parity tests: `32 passed`; native protocol and track
  state tests: `PASS`.
- Observability protocol amendment: W3C trace context and bounded native
  operation parity `49 passed`; C++ remains OTLP/network-free.
- Packet-wide Python unit/contract suite: `129 passed`; isolated persistence/API
  integration suite: `44 passed`.
- Existing native protocol/video aggregation binaries: `PASS`.
- Packet 3 Task 7 native RTSP ingest and live SGIE metadata coverage: `PASS`.
  The real GPU smoke used `nvurisrcbin`, NVDEC/NVMM, the existing
  YOLOv8-Face/NvDCF/GPU alignment/ArcFace chain and a 120-frame Friends window.
- Task 7 baseline raw summary: `120` decoded frames, `357` tracked/eligible
  objects, `357` normalized embeddings, `0` missing/invalid embeddings,
  norm min/max/mean `0.999999/1/1`, consecutive cosine mean `0.0817879` over
  `356` pairs, `0` measured tracker ID switches, `0` bus warnings/errors and
  exactly `2` sampled `inference_window` operation records.
- Task 7 one-variable A/B raw summaries:

  | Candidate | Coverage | Norm min/max/mean | Consecutive cosine mean / pairs | ID switches | Pipeline warnings/errors |
  |---|---:|---:|---:|---:|---:|
  | existing video configs | `357/357` | `0.999999/1/1` | `0.0817879 / 356` | `0` | `0/0` |
  | SGIE `network-type=100` | `357/357` | `0.999999/1/1` | `0.0817879 / 356` | `0` | `0/0` |
  | remove `operate-on-gie-id` | `357/357` | `0.999999/1/1` | `0.0817879 / 356` | `0` | `0/0` |
  | `secondary-reinfer-interval=1` | `357/357` | `0.999999/1/1` | `0.0817879 / 356` | `0` | `0/0` |
  | NvDCF `visualTrackerType=0` | `357/357` | `0.999999/1/1` | `0.0817879 / 356` | `0` | `2 tracker warnings / 0` |

  Common optional plugin-scanner warnings are runtime-image inventory noise and
  were unchanged. No candidate improved the baseline, so no `live_*` config was
  created; the existing video configs remain the live contract.
- Native RTSP reconnect, annotated RTSP output, snapshots and soak:
  `NOT_PROVEN`.
- OpenTelemetry trace continuity, telemetry privacy/cardinality, Collector,
  Prometheus, Loki, Tempo, Grafana dashboards/correlations, retention,
  fault-isolation and overhead A/B: `DESIGN_APPROVED`, implementation
  `NOT_STARTED`.
- No production volume reset or destructive data operation was performed.
