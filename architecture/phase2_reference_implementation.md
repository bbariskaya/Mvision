# Phase 2 — Video İşleme İçin Referans Implementasyon Analizi

Bu doküman, `requirements/videorequirements.md`’deki gereksinimlerin referans açık kaynak projelerde nasıl karşılandığını ve kendi implementasyonumuza uyarlayabileceğimiz yolları anlatır.

---

## 1. Phase 2 Kapsamı

Phase 1’deki imaj endpoint’lerine ek olarak:

- **Video upload** ile asenkron işlem başlatma.
- **Frame örnekleme** (sampling) — her N kare veya saniyede X kare.
- **Kareler arası yüz takibi** (tracking) aynı kişiye `trackId` atar.
- **Kişi bazında özetleme** — `firstSeen`, `lastSeen`, `totalDuration`, `appearances`, kare kare bbox detayları.
- **Video saklama/retention** — yüklenen videoları MinIO’da tutma, otomatik silme.
- **Asenkron job yönetimi** — `pending / processing / completed / failed`, iptal, ilerleme.
- **Geçmiş/ilişki sorgulama** — bir yüzün hangi videolarda ne zaman göründüğü.

---

## 2. Referans Projeler

### 2.1 `zhouyuchong/face-recognition-deepstream`

Phase 1 dokümanında detaylı incelenmiştir. Phase 2 açısından sağladıkları:

- `uridecodebin` ile **video dosyası** kaynağı.
- `nvtracker` ile kareler arası yüz takibi.
- SGIE sonrası probeda **kare kare embedding** çıkarımı.
- RTSP desteği (Phase 3 için de geçerlidir).

Eksikleri:

- Asenkron job yönetimi yok.
- Örnekleme yok (her kare işlenir).
- Kişi bazında zaman aggregasyonu yok.
- Video saklama/retention yok.

### 2.2 `Limitless-Blue/AI_Enhanced_Surveillance_System`

Bu proje, Phase 2’nin asenkron ve canlı kısımlarına çok yakın bir yapı sunar:

```
Browser  ←→  FastAPI (uvicorn)
                │
                ├── MongoDB (Motor async)
                ├── Celery + Redis (async workers)
                └── InsightFace + DeepSORT (video işleme)
```

#### Özellikler

- **Medya analizi**: Resim veya video yükle, arka planda işle.
- **Job progress tracking**: `GET /api/media/jobs` ile iş listesi.
- **Canlı kamera akışları**: RTSP/IP kamera kaydı, Celery worker’da ayrı task olarak çalıştırma, start/stop.
- **Frame skip**: Tanıma sıklığını ayarlama.
- **DeepSORT tracking**: Birden fazla kareden aynı kişiyi takip etme.
- **Embedding buffer**: Son 5 karenin embedding’ini ortalayarak gürültüyü azaltma.
- **Socket.IO**: İşlem ve tespit olaylarını ön yüze anlık iletme.

Phase 2 için alınacak ders:

- **FastAPI + Celery/Redis + MongoDB/PostgreSQL** kombinasyonu asenkron video işlemeye uygundur.
- Her video/job bir Celery task’ıdır; durum Redis/DB’de tutulur.
- Frame skip ve per-stream konfigürasyonu `env` / request parametresiyle yapılır.

### 2.3 `NNDam/deepstream-face-recognition`

Bu repo, DeepStream içinde **batchedNMS + landmark** kullanarak video dosyası üzerinde detection → alignment → feature extraction yapar:

```bash
LD_PRELOAD=<NMS-plugin> python main.py file:<video-input>
```

#### Özellikler

- Custom `batchedNMSDynamic_TRT` plugin ile NMS ve landmark çıkarımı.
- İki pipeline seçeneği:
  - `main.py`: person detection → face detection (crop) → face embedding
  - `main_ff.py`: full-frame face detection → face embedding

Eksikleri:

- Asenkron job yönetimi yok.
- Track ID / kişi bazlı özetleme yok.
- GPU alignment hâlâ TODO listesinde (repo README’sinde belirtilmiş).

### 2.4 `Abdirayimov/multi-stream-face-recognition`

Phase 3 için daha fazla referans olsa da, Phase 2’nin **batch/paralel işleme** kısmında dersler içerir:

- **ProbeChain**: Detections across streams/frame içeren batched alignment + encoding.
- **Batched TensorRT inference**: ArcFace için yüz crop’larını toplu işler.
- **FAISS GPU** ile hızlı similarity search.

Phase 2 için ders:

- Video frame’lerinden çıkan yüzleri toplu hale getirip tek ArcFace batch’iyle işlemek, uzun videolarda throughput’u artırır.

---

## 3. Phase 2 Mimari Blokları

### 3.1 Asenkron Job Worker

Video işleme uzun sürebileceğinden endpoint anında `jobId` döner:

```python
@router.post("/videos/recognize")
async def recognize_video(file: UploadFile):
    validate_file(file)
    minio_path = store_in_minio(file)
    job = process_video_task.delay(minio_path)
    return {"jobId": job.id, "status": "pending"}
```

Worker seçenekleri:

- **Celery + Redis**: En yaygın; task durumu, retry, iptal desteği var.
- **RQ + Redis**: Daha hafif; Redis backlog yönetimi.
- **Celery + RabbitMQ**: Daha sağlam mesaj garantisi.

Job durum modeli:

```python
class VideoJob:
    id: str
    status: "pending" | "processing" | "completed" | "failed" | "cancelled"
    progress: int
    minio_path: str
    result: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
```

İptal için Celery `revoke(task_id, terminate=True)` kullanılabilir.

### 3.2 Video Input ve Validation

```python
MAX_FILE_SIZE = int(os.getenv("VIDEO_MAX_FILE_SIZE_MB", 500)) * 1024 * 1024
MAX_DURATION_SEC = int(os.getenv("VIDEO_MAX_DURATION_SEC", 300))
ALLOWED_FORMATS = {"video/mp4", "video/avi", "video/quicktime"}
```

Adımlar:

1. MIME type ve boyut kontrolü.
2. `ffprobe` ile süre, fps, genişlik, yükseklik okunur.
3. Video MinIO’ya yazılır.
4. `VideoJob` kaydı PostgreSQL’de oluşturulur.

### 3.3 Frame Sampling

İki strateji:

- **Every N frames**: `sample_rate=10` → her 10 kareden biri.
- **Target FPS**: `target_fps=2` → orijinal fps’e göre atlama.

```python
def sample_frames(video_path, strategy="every_nth", value=10):
    cap = cv2.VideoCapture(video_path)
    frame_no = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if strategy == "every_nth" and frame_no % value == 0:
            yield frame_no, cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, frame
        frame_no += 1
    cap.release()
```

Worker içinde örneklenen frame’ler ya geçici dosyaya yazılıp DeepStream pipeline’a verilir, ya da doğrudan memory buffer/appsrc üzerinden beslenir.

### 3.4 DeepStream Video Pipeline

Phase 1’dekine benzer, ancak kaynak sürekli video akışıdır:

```
filesrc / appsrc → decode → nvstreammux → queue
→ PGIE (YOLOv8-Face + landmark)
→ nvtracker (NvDCF / IOU)
→ queue → SGIE (ArcFace)
→ queue → probe (metadata çıkarımı)
→ fakesink / filesink (opsiyonel annotated output)
```

Önemli farklar:

- `nvtracker` elementi eklenir; bu sayede aynı yüz ardışık karelerde `trackId` alır.
- Probe, her frame için şunları kaydeder:
  - `frame_num`
  - `timestamp_sec`
  - `track_id`
  - `face_id` (Qdrant match sonrası)
  - `bbox` (orijinal çözünürlüğe göre)
  - `embedding`
  - `confidence`

### 3.5 Kişi Bazında Aggregation

Probe’dan gelen kare kare kayıtlar bir dictionary’de toplanır:

```python
tracks = defaultdict(lambda: {
    "frames": [],
    "embeddings": [],
    "bboxes": [],
    "confidences": [],
})

for record in frame_records:
    tracks[record.track_id]["frames"].append(record.frame_num)
    tracks[record.track_id]["embeddings"].append(record.embedding)
    ...
```

Her track için:

1. Embedding’lerin ortalaması / en yüksek confidence’lı örnek seçilir.
2. Qdrant’a sorgu atılır:
   - Eşik üstünde bilinen yüzle eşleşirse `faceId` = known.
   - Eşleşmezse yeni `new_anonymous` faceId oluşturulur ve embedding kaydedilir.
3. Tüm frame’lerde görülen aralıklar `appearances` listesine dönüştürülür.

Çıktı (her kişi için):

```json
{
  "faceId": "face_001",
  "trackId": "track_a1",
  "status": "known",
  "firstSeen": 1.2,
  "lastSeen": 12.8,
  "totalDuration": 11.6,
  "appearances": [
    {"start": 1.2, "end": 12.8, "startFrame": 36, "endFrame": 384}
  ],
  "detections": [
    {"frame": 36, "timestamp": 1.2, "boundingBox": {...}, "confidence": 0.93}
  ]
}
```

#### Identity Resolution (Track → Face)

Bir track boyunca her karede farklı sonuç çıkabilir (kiminde known, kiminde anonymous). Karar stratejileri:

- **En yüksek confidence**: Track içindeki en yüksek skorlu eşleşmeyi al.
- **Çoğunluk oylaması**: known/anonymous/new_anonymous sayısına göre karar ver.
- **Ortalama embedding**: Track embedding’lerinin ortalamasıyla tek sorgu yap.

### 3.6 Koordinat Dönüşümü

DeepStream pipeline’da işleme 640×640 veya 1280×1280 gibi sabit boyutta yapılabilir. `bbox` koordinatları orijinal video çözünürlüğüne şu şekilde dönüştürülür:

```python
scale_x = original_width / processing_width
scale_y = original_height / processing_height
bbox_original = {
    "x": bbox.x * scale_x,
    "y": bbox.y * scale_y,
    "width": bbox.width * scale_x,
    "height": bbox.height * scale_y,
}
```

Bu işlem, ölçekleme durumunda bile istemcinin orijinal video üzerine doğrudan çizim yapabilmesini sağlar.

### 3.7 Retention ve MinIO

```python
VIDEO_RETENTION_DAYS = int(os.getenv("VIDEO_RETENTION_DAYS", 7))
MINIO_BUCKET = os.getenv("MINIO_VIDEO_BUCKET", "videos")
```

- Yüklenen video `MinIO`’ya `{job_id}/input.mp4` olarak yazılır.
- İşlem tamamlandığında sonuç JSON’u ayrı bir obje olarak saklanır.
- Günlük/periyodik bir cleanup görevi, retention süresi dolan videoları siler.

### 3.8 Process Logging ve Geçmiş

Her video işlemi için PostgreSQL’de iki kayıt:

1. `process_log` tablosu:
   - `process_id`, `job_id`, `video_metadata`, `person_count`, `face_ids`, `status`, `timestamp`.
2. `face_appearance` tablosu:
   - `face_id`, `job_id`, `video_path`, `timestamps`, `frame_numbers`.

Böylece `GET /faces/{faceId}/appearances` sorgusu sadece bu tabloya bakarak cevap verir.

---

## 4. API Endpoint Eşleştirmesi

| Endpoint | Sorumlu Bileşen | Not |
|---|---|---|
| `POST /videos/recognize` | FastAPI + Celery worker | Upload kabul eder, jobId döner. |
| `GET /videos/jobs/{jobId}` | FastAPI + DB | `pending/processing/completed/failed` + progress. |
| `GET /videos/jobs/{jobId}/result` | FastAPI + DB/MinIO | Aggregation sonuç JSON’u döner. |
| `DELETE /videos/jobs/{jobId}` | FastAPI + Celery | Workerı iptal eder, kaydı siler. |
| `GET /faces/{faceId}/appearances` | FastAPI + PostgreSQL | Yüzün hangi videolarda ne zaman göründüğü. |
| `GET /processes/{processId}` | FastAPI + PostgreSQL | İşlem detayı ve metadata. |

---

## 5. Zorluklar ve Dikkat Edilecekler

### Sparse Sampling ve Tracker

Eğer örnekleme çok seyrek olursa (`örn. her 30 kare`), `nvtracker` aynı kişiyi doğru takip edemeyebilir. Bunun için:

- `nvtracker`’ın `probationAge` / `shadowAge` parametreleri artırılır.
- Track ID’ler arası geçişlerde embedding ortalaması kullanılarak identity kalıcılığı sağlanır.

### Bellek Yönetimi

Uzun videolarda tüm frame kayıtlarını bellekte tutmak yerine:

- Parça parça (chunk) işleme.
- Her chunk aggregation’ından sonra sonuç diske yazılır.

### Dynamic Batch

Phase 1’deki dynamic batch model aynen kullanılır. `streammux.batch-size` ve video worker’ın aynı anda işlediği frame sayısı eşleştirilir.

---

## 6. Sonuç

Phase 2, Phase 1’in aynı GPU inference zincirini video + tracker + aggregation ile genişletir. Referans projelerden:

- `zhouyuchong/face-recognition-deepstream` → tracker + per-frame embedding çıkarımı.
- `Limitless-Blue/AI_Enhanced_Surveillance_System` → asenkron job mimarisi, Celery/Redis, progress tracking.
- `Abdirayimov/multi-stream-face-recognition` → batched alignment/encoding optimizasyonu.

derslerini alarak kendi implementasyonumuzu inşa edebiliriz.

---

## Kaynaklar

- `zhouyuchong/face-recognition-deepstream` — https://github.com/zhouyuchong/face-recognition-deepstream
- `Limitless-Blue/AI_Enhanced_Surveillance_System` — https://github.com/Limitless-Blue/AI_Enhanced_Surveillance_System
- `NNDam/deepstream-face-recognition` — https://github.com/NNDam/deepstream-face-recognition
- `Abdirayimov/multi-stream-face-recognition` — https://github.com/Abdirayimov/multi-stream-face-recognition
