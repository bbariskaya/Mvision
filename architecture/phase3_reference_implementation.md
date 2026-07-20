# Phase 3 — Canlı Akış (Live Streaming) İçin Referans Implementasyon Analizi

Bu doküman, Phase 1 (image) ve Phase 2 (video upload) sonrasında **çoklu canlı kamera/RTSP akışı** gereksinimlerinin açık kaynak projelerde nasıl karşılandığını ve kendi implementasyonumuza nasıl uyarlayacağımızı anlatır.

---

## 1. Phase 3 Kapsamı

Phase 1 ve Phase 2’deki yeteneklere ek olarak:

- **RTSP/IP/USB kamera kaynakları** ile sürekli canlı işlem.
- **Çoklu kamera** desteği — aynı anda N kameredan yüz tanıma.
- **Dinamik kaynak yönetimi** — kamera ekleme, çıkarma ve yeniden bağlanma.
- **Gerçek zamanlı event bus** — eşleşme/anonymous/zone olaylarını anlık iletme.
- **Cross-camera re-identification** — aynı kişinin farklı kameralardaki track’lerini ilişkilendirme.
- **Canlı görsel çıkış** (opsiyonel) — annotate edilmiş RTSP/WebRTC/HLS feed.
- **Stream metadata** — `streamId`, `cameraId`, `timestamp`, `firstSeen`, `lastSeen` gibi alanlar.
- **Alert dispatch** — webhook, Telegram, e-posta, ntfy gibi kanallarla anlık bildirim.

---

## 2. Referans Projeler

### 2.1 `Abdirayimov/multi-stream-face-recognition`

En teknik olarak güçlü referans. Saf C++17 + CMake, NVIDIA DeepStream 7.x/8.x + TensorRT.

```
RTSP / file ──▶ uridecodebin ──▶ nvstreammux ──▶ nvinfer (SCRFD)
                                                          │
                                               src-pad probe (tensor parse)
                                                          ▼
                                  ┌────────────────────────────────────────┐
                                  │              ProbeChain                │
                                  │  ┌─────────┐  ┌─────────┐  ┌────────┐  │
                                  │  │  align  │─▶│ encode  │─▶│ FAISS  │  │
                                  │  │ 5-point │  │ ArcFace │  │ search│  │
                                  │  └─────────┘  └─────────┘  └────────┘  │
                                  └────────────────────────────────────────┘
                                                          │
                                                          ▼
                                            FrameResult callback → log/Redis/DB
```

#### Özellikler

- **Multi-camera DeepStream pipeline** — `add_source` / `remove_source` API ile çalışma zamanında kaynak değiştirme.
- **Batched inference** — Tek kare içinde tüm kameralardan gelen yüz crop’larını biriktirip tek ArcFace batch’inde encode eder.
- **5-point Umeyama alignment** — GPU/CPU benzer dönüşüm.
- **FAISS GPU** — `IVF-Flat` (≤100K) ve otomatik `IVF-PQ` (>100K).
- **Stream plumbing odaklı** — RTSP stall, backpressure, EOS, graceful source removal konularını açıkça ele alır.

#### Eksikleri

- REST/gRPC yüzeyi yok; yalnızca programatik C++ API.
- Kalıcı enrollment DB yok; FAISS index dosyası doğrudan yazılır.
- Alert/event dispatch yok.

#### Uyarlanacak Dersler

- `nvstreammux` + custom probe chain ile **cross-stream batching** yapılabilir.
- FAISS GPU yerine bizim zaten kullandığımız **Qdrant** ile devam edilebilir; büyük ölçekte yeterli.
- Dynamic source ekleme/çıkarma için DeepStream `nvurisrcbin`+`add_source` pattern’i kullanılır.

---

### 2.2 `Limitless-Blue/AI_Enhanced_Surveillance_System`

Python merkezli, üretim odaklı bir FastAPI platformu. InsightFace `buffalo_l` paketini kullanıyor.

```
Browser  ←→  FastAPI (uvicorn) ←──── Redis Pub/Sub ────▶ Celery workers
                 │                                            │
                 ▼                                            ▼
              MongoDB                                  InsightFace + DeepSORT
```

#### Özellikler

- **Canlı RTSP/IP/USB kamera kayıt ve yönetimi** — `POST /api/cameras`, `/cameras/{id}/start`, `/stop`.
- **Per-camera Celery task** — Her kamera ayrı worker task’idir; frame skip ve threshold konfigürasyonu her kameraya özel.
- **DeepSORT tracking** — Kareler arası `track_id` sabitleme.
- **5-frame embedding buffer** — Hareket bulanıklığından gelen gürültüyü ortalama embedding ile azaltma.
- **Socket.IO** — Tespit/alert olaylarını ön yüze canlı iletme.
- **Multi-channel alert** — Telegram, Gmail SMTP, ntfy.sh, HTTP webhook.

#### Eksikleri

- Tüm inference CPU/GPU karışık InsightFace python pipeline üzerinde; DeepStream’in tam GPU zero-copy avantajı yok.
- Büyük ölçekli çoklu kamera için tek worker task başına model yükleme maliyetli.

#### Uyarlanacak Dersler

- **FastAPI + Celery + Redis + Socket.IO** kombinasyonu canlı stream yönetimi için uygundur.
- Kamera başına **bağımsız worker/process** ve **start/stop lifecycle** API’leri uygulanmalı.
- Embedding buffer ve temporal smoothing için aynı pattern kullanılabilir.

---

### 2.3 `wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline`

DeepStream üzerinden çok kamera, tracking, ReID ve event çıkaran C++ referans.

```
[ RTSP Cameras ]
        │
        ▼
C++ Core Engine (DeepStream 6.2)
  • PGIE PeopleNet ResNet-34 INT8
  • nvDCF tracker (per camera)
  • SGIE ReID ResNet50 FP16
  • Cross-camera gallery cosine matching
  • pad probe → JSONL events → ZeroMQ
        │
        ▼
Application Layer (FastAPI) — planned
```

#### Özellikler

- **Multi-stream RTSP ingestion** ve **batched mux** (`nvstreammux`).
- **Pad probe SGIE src-pad’de** — PGIE + tracker + SGIE tamamlandıktan sonra embedding okunur.
- **Cross-camera global ID** — Her kamera için ayrı `tid` alınır, kamera dışı galeride cosine similarity ile aynı kişiye global ID atanır.
- **ZMQ PUB/SUB** ile **non-blocking** event gönderimi; yavaş consumer pipeline’ı durdurmaz.
- **NvDCF Dummy mode** (`visualTrackerType=0`) ile correlation filter’dan kaynaklanan NVMM çekişmesini engelleme.

#### Eksikleri

- Yüz tanıma değil, person ReID odaklı; ama pipeline pattern doğrudan yüze uyarlanır.
- FastAPI control plane henüz tamamlanmamış (Phase 5+).

#### Uyarlanacak Dersler

- **SGIE’nin tracker’dan sonra** konumlandırılması zorunlu; aksi halde tensor meta kaybolur.
- **Cross-camera re-id** için probeda bellek içi galeri ve global ID atama mekanizması.
- ZeroMQ benzeri bir event bus (bizde Redis Pub/Sub) ile **decoupled, non-blocking** çıkış.

---

### 2.4 `OcelStream/Osprey`

DeepStream 8.0 tabanlı, REST API ile dinamik kaynak yönetimi yapan modern platform.

```
REST API  ──▶  DeepStream pipeline  ──▶  per-stream Unix socket
POST /add                                      │
DELETE /remove                                 ▼
                                       DeepStreamClient (container)
                                       ──▶  rtsp://host:8557/<stream_id>
```

#### Özellikler

- **Runtime source add/remove** — Zero downtime.
- **Her stream için ayrı RTSP çıkışı** — `rtsp://localhost:8557/ds-test<stream_id>`.
- **Unix domain socket** ile zero-copy IPC.
- **FastAPI + DeepStream C++ engine** ayrı konteynerlerde.

#### Uyarlanacak Dersler

- Canlı kameralardan annotate edilmiş RTSP çıkışı istenirse bu yapı kullanılabilir.
- Her kameraya özel **stream_id** ve **demux + ayrı encoder** mantığı.

---

### 2.5 `iam-ajmunna/ha_meem_ai_surveillance`

Fabrika giriş alanı için üretim odaklı DeepStream 7.0 sistem.

- **Modeller**: SCRFD detector + **AdaFace** recognizer + FAISS matcher.
- **Diller**: Python ve C++ DeepStream pipeline, `core/` kütüphaneler ortak.
- **Konteyner**: `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`.
- **Galeri oluşturma**: `extract_faces` → `build_gallery`.

#### Özellikler

- AdaFace, düşük kaliteli görüntüler için ArcFace’e alternatif; biz ArcFace R50 ile devam ediyoruz ancak AdaFace bilgisi not edildi.
- C++ ve Python pipeline seçenekleri aynı `core/` ile paylaşıyor.

#### Uyarlanacak Dersler

- C++ DeepStream motorunu Python FastAPI’dan bağımsız tutup ortak `core/` kütüphanelerle entegre etme fikri.
- FAISS/Qdrant/Disk tabanlı galeri yönetimi için ayrı enrollment araçları (`build_gallery`).

---

### 2.6 NVIDIA `deepstream-rtsp-in-rtsp-out`

Resmi DeepStream Python örneği.

- RTSP input → inference → RTSP output (`rtsp://host:8554/ds-test`).
- `GstRtspServer` ile çıkış sunma.
- Canlı çıkış branch’ini ilk elden test etmek için iyi başlangıç.

---

## 3. Phase 3 Mimari Blokları

### 3.1 Kamera Yaşam Döngüsü (Camera Lifecycle)

Her kamera bir kayıt + bir çalışan işlem/task olarak yönetilir:

```python
class Camera:
    id: uuid
    name: str
    uri: str              # rtsp://..., /dev/video0, file://...
    enabled: bool
    config: CameraConfig  # fps, frame_skip, threshold, zones...
    status: "idle" | "running" | "error" | "reconnecting"
    pid: str | None       # worker process/task id
    created_at: datetime
    updated_at: datetime
```

İşlem seçenekleri:

- **Ayrı Celery task** başına kamera (Limitless-Blue yaklaşımı) — basit ama model başına yeniden yüklenir.
- **Tek DeepStream C++ process + dinamik `add_source/remove_source`** (Abdirayimov/Osprey yaklaşımı) — tercih edilen, daha az bellek/GPU; FastAPI onu yönetir.

API:

| Method | Endpoint | Açıklama |
|---|---|---|
| `POST` | `/cameras` | Yeni kamera kaydı oluştur |
| `GET` | `/cameras` | Kameraları listele |
| `POST` | `/cameras/{id}/start` | Akışı başlat |
| `POST` | `/cameras/{id}/stop` | Akışı durdur |
| `DELETE` | `/cameras/{id}` | Kaydı ve akışı kaldır |
| `GET` | `/cameras/{id}/status` | Durum, FPS, son görülen frame zamanı |

---

### 3.2 Kaynak ve Yeniden Bağlanma Yönetimi

DeepStream tarafında:

```
uridecodebin / nvurisrcbin ──▶ nvvideoconvert ──▶ nvstreammux
```

- **RTSP stall** durumunda `rtspsrc` reconnect yapılandırması (`timeout`, `latency`, `drop-on-latency=true`).
- `nvstreammux` **live-source=1** ve **batched-push-timeout** ayarları; karelerin beklemesi yerine mümkün olan en kısa sürede batch oluşturulur.
- **Source watchdog**: Belirli süre frame gelmezse `remove_source` + `add_source` ile yeniden bağlan.

```python
# Pseudo state machine
state = running
if no_frame_for(seconds=RECONNECT_TIMEOUT):
    state = reconnecting
    pipeline.remove_source(camera.id)
    pipeline.add_source(camera.uri, camera.id)
    state = running
```

---

### 3.3 GPU Pipeline (Phase 1/2 ile Aynı, Farklar İşaretlendi)

```
[source 1..N] ──▶ nvstreammux
                      │
                      ▼
              PGIE YOLOv8-Face (dynamic batch, 5 landmark)
                      │
                      ▼
              nvtracker (NvDCF/IoU)
                      │
                      ▼
              nvdspreprocess (CustomTensorPreparation: 5-point → 112×112)
                      │
                      ▼
              SGIE ArcFace R50
                      │
                      ▼
              pad probe (metadata çıkarımı)
                      │
              ┌───────┴───────┐
              ▼               ▼
        event bus            (opsiyonel) demux → encode → RTSP/HLS
```

Farklar:

- `nvtracker` **live source** modu için konfigüre edilir (`config_tracker_NvDCF_live.yml`).
- SGIE’den önce **nvdspreprocess** eklenir Phase 1’deki alignment’ı GPU’da tutmak için.
- Probe, **stream_id + timestamp + track_id** ile çıkarım yapar.

---

### 3.4 Probe ve Temporal Aggregation

Canlı akışta her frame’de Qdrant sorgusu yapmak yerine **track başına temporal smoothing** uygulanır:

```python
class LiveTrackState:
    track_id: int
    stream_id: str
    embeddings: deque[Embedding]  # son N embedding
    confidences: deque[float]
    last_seen_at: float
    face_id: str | None
    status: "unknown" | "known" | "pending"
```

Karar kuralları:

1. Track’in son 10 embedding’inin ortalamasını al.
2. Qdrant’ta cosine similarity search (top-1).
3. Eşik üzerindeyse `face_id` sabitlenir; altındaysa `anonymous_<track_id>`.
4. Aynı track içinde geçici değişimlerde **hysteresis** — `pending` durumundan known/unknown geçiş için 3 kare üst üste aynı sonuç gerekir.

---

### 3.5 Cross-Camera Re-Identification

Aynı kişi farklı kameralarda farklı `track_id` alır. Cross-camera ID için iki seçenek:

**Seçenek A — Central gallery (wjli699 tarzı)**

- Her `known` eşleşme, global bellek içi galeriye `(face_id, embedding, last_seen_camera, last_seen_at)` olarak eklenir.
- Yeni kamerada unknown track oluşunca, track embedding’i galerideki diğer kamera kayıtlarıyla karşılaştırılır.
- Benzerlik ≥ threshold ise aynı `face_id` atanır, aksi halde yeni anonymous ID.

**Seçenek B — Qdrant merkezli**

- Her track average embedding doğrudan Qdrant’a sorgulanır.
- Qdrant zaten merkezi galeri görevi görür; cross-camera eşleşme de buradan döner.
- Basit ve tutarlı; Phase 1/2 ile aynı arama katmanı.

Önerimiz **Seçenek B**.

---

### 3.6 Gerçek Zamanlı Event Bus

```
Probe ──▶ Redis Pub/Sub (channel: detections) ──▶ FastAPI Socket.IO/WebSocket ──▶ Clients
        │
        └─▶ PostgreSQL (event log)
        └─▶ Alert dispatcher (webhook, Telegram, email)
```

Event şeması:

```json
{
  "event": "face.recognized",
  "streamId": "cam-1",
  "cameraId": "uuid",
  "timestamp": "2026-07-20T12:34:56Z",
  "trackId": 42,
  "faceId": "face_001",
  "status": "known",
  "confidence": 0.91,
  "boundingBox": {"x": 120, "y": 80, "width": 60, "height": 80}
}
```

- **Non-blocking**: Probe, kare işleme hızını düşürmemesi için event dispatch’i asyncio thread veya Redis pipeline ile asenkron yapar.
- **Deduplikasyon**: Aynı track’ten saniyede birden fazla event üretmeyi önlemek için `min_event_interval_ms` konfigürasyonu.

---

### 3.7 Canlı Görsel Çıkış (Opsiyonel)

DeepStream’ten anotasyonlu görüntü çıkışı için:

```
nvstreamdemux ──▶ nvvideoconvert ──▶ nvdsosd (bbox + label)
                                 ──▶ nvv4l2h264enc ──▶ h264parse ──▶ rtph264pay
                                 ──▶ GstRtspServer (rtsp://host:8554/live/<stream_id>)
```

Alternatif olarak WebRTC/HLS sunucuları (ör. `aiortc`, `mediamtx`) ile entegrasyon.

---

### 3.8 Alert Dispatch

Phase 3’te opsiyonel olarak:

- `face.recognized.known` — izin listesi/denetim listesi eşleşmeleri.
- `face.recognized.unknown` — tanımlanamayan kişi belirli süre görülürse.
- `zone.intrusion` — tanımlı polygon bölgelere giriş/çıkış.
- Kanallar: webhook, Telegram bot, e-posta, ntfy.

---

## 4. API Endpoint Eşleştirmesi

| Endpoint | Sorumlu Bileşen | Not |
|---|---|---|
| `POST /cameras` | FastAPI + DB | Yeni kamera kaydı. |
| `GET /cameras` | FastAPI + DB | Liste. |
| `POST /cameras/{id}/start` | FastAPI → DeepStream manager | Akış başlat. |
| `POST /cameras/{id}/stop` | FastAPI → DeepStream manager | Akış durdur. |
| `DELETE /cameras/{id}` | FastAPI + DB + Manager | Çalışıyorsa önce durdur, sonra sil. |
| `GET /cameras/{id}/status` | FastAPI + DeepStream manager | FPS, son kare, hata. |
| `GET /cameras/{id}/snapshots` | FastAPI + MinIO/FS | Son N anlık görüntü. |
| `WS /live/detections` | FastAPI + Redis Pub/Sub | Canlı event akışı. |
| `POST /alerts/rules` | FastAPI + DB | Alert kuralı tanımla. |

---

## 5. Zorluklar ve Dikkat Edilecekler

### RTSP Yeniden Bağlanma ve Stall

- `uridecodebin` ile her kamera ayrı source bin’dir; kamera düştüğünde `remove_source` ardından `add_source` yapılmalı.
- `nvstreammux` timeout çok kısa olursa boş batch’ler gider, çok uzunsa latency artar.

### Canlı Tracker Ayarları

- `NvDCF`’in default config’i file-based kaynaklara göredir; live source için `visualTrackerType=0` (DUMMY) seçeneği denenmeli.
- `maxShadowTrackingAge` ve `probationAge` artırılarak kısa süreli oklüzyon/latency toleransı sağlanır.

### Cross-Camera Timestamp Senkronizasyonu

- Kameraların kendi RTC’leri farklı olabilir; NTP senkronizasyonu veya RTCP sender report timestamp’leri tercih edilir.
- DeepStream `--rtsp-ts` ile RTSP kaynağın timestamp’ini frame meta’ya taşıyabilir.

### GPU Bellek ve Stream Sayısı

- Quadro RTX 8000 48 GB × 3 ile onlarca 1080p akış mümkün, ancak her kaynak decode + inference + tracker bellek harcar.
- Stream sayısı arttıkça `nvstreammux` batch-size ve `batched-push-timeout` yeniden ayarlanmalı.

### Event Bus Non-blocking

- Probe içinde sync HTTP çağrısı yapmak pipeline’ı kilitler. Eventleri kuyruğa atıp ayrı bir task/worker dispatch etmeli.

---

## 6. Sonuç

Phase 3, Phase 1 ve Phase 2’nin aynı GPU inference zincirini **sürekli canlı akışlara** taşır. Referanslardan:

- `Abdirayimov/multi-stream-face-recognition` → DeepStream C++’ta **dynamic multi-source**, **batched probe chain**, **FAISS/Qdrant** entegrasyonu.
- `Limitless-Blue/AI_Enhanced_Surveillance_System` → **FastAPI + Celery + Redis + Socket.IO** ile kamera yaşam döngüsü ve anlık event mimarisi.
- `wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline` → **SGIE src-pad probe**, **cross-camera global ID**, **ZeroMQ decoupling** pattern’leri.
- `OcelStream/Osprey` → **dinamik source add/remove** ve **RTSP çıkış branch**.

Bu parçaları birleştirerek kendi canlı streaming sistemimizi inşa edebiliriz.

---

## Kaynaklar

- `Abdirayimov/multi-stream-face-recognition` — https://github.com/Abdirayimov/multi-stream-face-recognition
- `Limitless-Blue/AI_Enhanced_Surveillance_System` — https://github.com/Limitless-Blue/AI_Enhanced_Surveillance_System
- `wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline` — https://github.com/wjli699/DeepStream-Multi-Stream-Video-Intelligence-Pipeline
- `OcelStream/Osprey` — https://github.com/OcelStream/Osprey
- `iam-ajmunna/ha_meem_ai_surveillance` — https://github.com/iam-ajmunna/ha_meem_ai_surveillance
- `NVIDIA-AI-IOT/deepstream_python_apps` (`deepstream-rtsp-in-rtsp-out`) — https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/tree/master/apps/deepstream-rtsp-in-rtsp-out
