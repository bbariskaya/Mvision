# Phase 1 — GPU-Hot Face Recognition API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Dockerized FastAPI service that detects and recognizes faces in uploaded images using a single end-to-end DeepStream + TensorRT pipeline that keeps frames on the GPU through detection, alignment, and recognition.

**Architecture:** FastAPI receives an image, stores it in MinIO, and runs a DeepStream pipeline per request. The pipeline uses YOLOv8-Face as PGIE, a custom `nvdspreprocess` C++/CUDA library for 5-point alignment, ArcFace R50 dynamic-batch as SGIE, and a pad probe that sends embeddings to the Python layer. The Python layer queries Qdrant for identity, assigns face IDs, and logs the process in PostgreSQL.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy + asyncpg, Alembic, Qdrant, MinIO, DeepStream Python bindings, TensorRT, OpenCV.

## Global Constraints

- CUDA 13 / NVIDIA driver on host; container uses a DeepStream CUDA image matching host capabilities.
- All models live under `models/` in the repo; TensorRT engines are generated inside the container on first run.
- No comments in source unless explicitly requested.
- `arcface_r50_dynamic.onnx` already includes input pixel normalization and output L2 normalization, so DeepStream config must use `net-scale-factor=1.0` and `offsets=0`.
- `yolov8n-face.onnx` outputs 5 facial landmarks used for alignment.
- All persistent data survives container restart.
- Environment variables drive configuration.

---

## File Structure

- `docker-compose.yml` — API, PostgreSQL, Qdrant, MinIO services.
- `backend/Dockerfile` — DeepStream + Python environment image.
- `backend/requirements.txt` — Python dependencies.
- `backend/src/config.py` — Pydantic settings.
- `backend/src/db/` — SQLAlchemy models, async session, Alembic migrations.
- `backend/src/gallery/` — Qdrant collection + gallery CRUD/search service.
- `backend/src/pipeline/` — DeepStream Python pipeline, probe handler, and a small C++/CUDA `nvdspreprocess` alignment plugin.
- `backend/src/recognition/` — Face matching logic, threshold rules, face ID assignment.
- `backend/src/process/` — Process logging service.
- `backend/src/api/` — FastAPI routers.
- `backend/src/main.py` — FastAPI app factory.
- `backend/tests/` — pytest tests.
- `models/` — `yolov8n-face.onnx`, `arcface_r50_dynamic.onnx`, and generated `.engine` files.
- `configs/` — DeepStream nvinfer config `.txt` files for PGIE and SGIE.

---

## Task 1: Docker Compose Infrastructure

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `backend/requirements.txt`

**Interfaces:**
- Produces: `api` service reachable on `API_PORT`, `postgres` on `5432`, `qdrant` on `6333`, `minio` on `9000`/`9001`.
- Consumes: host NVIDIA runtime and `models/` directory.

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-mvision}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mvision}
      POSTGRES_DB: ${POSTGRES_DB:-mvision}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "${POSTGRES_PORT:-5432}:5432"

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant:/qdrant/storage
    ports:
      - "${QDRANT_PORT:-6333}:6333"

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD:-minioadmin}
    volumes:
      - minio:/data
    ports:
      - "${MINIO_API_PORT:-9000}:9000"
      - "${MINIO_CONSOLE_PORT:-9001}:9001"

  api:
    build:
      context: .
      dockerfile: backend/Dockerfile
      args:
        DEEPSTREAM_IMAGE: ${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:7.1-triton-multiarch}
    runtime: nvidia
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql+asyncpg://mvision:mvision@postgres:5432/mvision}
      QDRANT_URL: ${QDRANT_URL:-http://qdrant:6333}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY:-minioadmin}
      MINIO_BUCKET_IMAGES: ${MINIO_BUCKET_IMAGES:-images}
    volumes:
      - ./models:/app/models:ro
      - ./configs:/app/configs:ro
      - ./backend/src:/app/src:ro
      - api_engines:/app/engines
    ports:
      - "${API_PORT:-8000}:8000"
    depends_on:
      - postgres
      - qdrant
      - minio

volumes:
  pgdata:
  qdrant:
  minio:
  api_engines:
```

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
ARG DEEPSTREAM_IMAGE=nvcr.io/nvidia/deepstream:7.1-triton-multiarch
FROM ${DEEPSTREAM_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Make DeepStream Python bindings available if not already on path
ENV PYTHONPATH="/opt/nvidia/deepstream/deepstream/sources/deepstream_python_apps/apps:${PYTHONPATH}"
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

COPY . .

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create `backend/requirements.txt`**

```text
fastapi==0.111.0
uvicorn[standard]==0.30.0
pydantic==2.7.0
pydantic-settings==2.3.0
sqlalchemy[asyncpg]==2.0.30
alembic==1.13.0
qdrant-client==1.9.0
minio==7.2.0
python-multipart==0.0.9
aiofiles==23.2.0
opencv-python-headless==4.9.0.80
onnxruntime-gpu==1.18.0
numpy==1.26.0
pytest==8.2.0
httpx==0.27.0
```

- [ ] **Step 4: Build image**

Run: `docker compose build api`
Expected: image builds without errors.

---

## Task 2: Configuration

**Files:**
- Create: `backend/src/config.py`

**Interfaces:**
- Produces: `Settings` singleton with DB, Qdrant, MinIO, model, and threshold values.

- [ ] **Step 1: Write the config module**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    api_port: int = 8000

    database_url: str = "postgresql+asyncpg://mvision:mvision@postgres:5432/mvision"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "face_samples_arcface_r50_webface_v1"
    qdrant_vector_size: int = 512
    qdrant_distance: str = "Cosine"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_images: str = "images"

    pgie_config_path: str = "/app/configs/pgie_yolov8n_face.txt"
    sgie_config_path: str = "/app/configs/sgie_arcface.txt"
    tracker_config_path: str = "/app/configs/config_tracker_NvDCF_perf.yml"

    recognition_threshold: float = 0.55
    anonymous_threshold: float = 0.40
    min_confidence: float = 0.25


settings = Settings()
```

- [ ] **Step 2: Run a smoke test**

Run: `python -c "from src.config import settings; print(settings.qdrant_collection)"`
Expected: `face_samples_arcface_r50_webface_v1`

---

## Task 3: Database Models and Migrations

**Files:**
- Create: `backend/src/db/__init__.py`
- Create: `backend/src/db/base.py`
- Create: `backend/src/db/session.py`
- Create: `backend/src/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/.gitkeep`

**Interfaces:**
- Produces: async SQLAlchemy session and `FaceRecord`, `Enrollment`, `ProcessLog`, `FaceAppearance` models.

- [ ] **Step 1: Write `backend/src/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Write `backend/src/db/models.py`**

```python
import datetime
import uuid
from sqlalchemy import String, DateTime, Float, Integer, JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class FaceRecord(Base):
    __tablename__ = "face_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    status: Mapped[str] = mapped_column(String(16), default="anonymous")
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


class ProcessLog(Base):
    __tablename__ = "process_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    task_type: Mapped[str] = mapped_column(String(32))
    processed_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    face_count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FaceAppearance(Base):
    __tablename__ = "face_appearances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    face_id: Mapped[str] = mapped_column(String(36), ForeignKey("face_records.id"), index=True)
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_logs.id"), index=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    confidence: Mapped[float] = mapped_column(Float)
    bounding_box: Mapped[dict] = mapped_column(JSON)
```

- [ ] **Step 3: Write `backend/src/db/session.py`**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.config import settings

engine = create_async_engine(settings.database_url, future=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 4: Initialize Alembic**

Run: `cd backend && alembic init alembic`
Expected: `alembic/` directory created.

- [ ] **Step 5: Configure Alembic for async**

Modify `backend/alembic/env.py` to use `Base.metadata` and async driver.

- [ ] **Step 6: Generate and run initial migration**

Run: `cd backend && alembic revision --autogenerate -m "init" && alembic upgrade head`
Expected: tables created in PostgreSQL.

---

## Task 4: Qdrant Collection and Gallery Service

**Files:**
- Create: `backend/src/gallery/client.py`
- Create: `backend/src/gallery/service.py`

**Interfaces:**
- Produces: `GalleryClient` with `ensure_collection`, `upsert`, `search`, `delete`.
- Consumes: `settings` and SQLAlchemy `FaceRecord`.

- [ ] **Step 1: Write `backend/src/gallery/client.py`**

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from src.config import settings


class GalleryClient:
    def __init__(self) -> None:
        self.client = QdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self.vector_size = settings.qdrant_vector_size
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )

    def upsert(self, face_id: str, embedding: list[float], payload: dict | None = None) -> None:
        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=face_id, vector=embedding, payload=payload or {})],
        )

    def search(self, embedding: list[float], top_k: int = 1, threshold: float = 0.0):
        results = self.client.search(
            collection_name=self.collection,
            query_vector=embedding,
            limit=top_k,
            score_threshold=threshold,
        )
        return results

    def delete(self, face_id: str) -> None:
        self.client.delete(collection_name=self.collection, points_selector=[face_id])
```

- [ ] **Step 2: Write `backend/src/gallery/service.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db.models import FaceRecord
from src.gallery.client import GalleryClient


gallery_client = GalleryClient()


class GalleryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = gallery_client

    async def enroll_face(self, face_id: str, embedding: list[float], name: str, metadata: dict | None = None) -> FaceRecord:
        record = await self.db.get(FaceRecord, face_id)
        if record is None:
            record = FaceRecord(id=face_id, status="known", name=name, metadata_json=metadata or {})
            self.db.add(record)
        else:
            record.status = "known"
            record.name = name
            record.metadata_json = metadata or {}
        self.client.upsert(face_id, embedding, {"name": name})
        await self.db.commit()
        return record

    async def find_match(self, embedding: list[float], threshold: float):
        hits = self.client.search(embedding, top_k=1, threshold=threshold)
        if not hits:
            return None
        return hits[0]

    async def get_face(self, face_id: str) -> FaceRecord | None:
        return await self.db.get(FaceRecord, face_id)

    async def delete_face(self, face_id: str) -> None:
        record = await self.db.get(FaceRecord, face_id)
        if record:
            await self.db.delete(record)
            self.client.delete(face_id)
            await self.db.commit()
```

- [ ] **Step 3: Add a unit test for Qdrant client**

Create `backend/tests/test_gallery.py`:

```python
import pytest
from src.gallery.client import GalleryClient


def test_gallery_search():
    client = GalleryClient()
    embedding = [0.0] * 512
    client.upsert("test-face-1", embedding)
    results = client.search(embedding, top_k=1, threshold=0.0)
    assert len(results) == 1
    assert results[0].id == "test-face-1"
```

Run: `cd backend && pytest tests/test_gallery.py -v`
Expected: PASS

---

## Task 5: DeepStream Config Files

**Files:**
- Create: `configs/pgie_yolov8n_face.txt`
- Create: `configs/sgie_arcface.txt`
- Create: `configs/config_tracker_NvDCF_perf.yml` (optional for Phase 1)

**Interfaces:**
- Produces: nvinfer configs consumed by `backend/src/pipeline/deepstream_pipeline.py`.

- [ ] **Step 1: Write `configs/pgie_yolov8n_face.txt`**

```ini
[property]
gpu-id=0
net-scale-factor=0.00392156862745098
model-color-format=0
model-engine-file=/app/engines/yolov8n-face.onnx_b1_gpu0_fp16.engine
onnx-file=/app/models/yolov8n-face.onnx
labelfile-path=/app/configs/labels_face.txt
batch-size=1
network-mode=2
num-detected-classes=1
interval=0
gie-unique-id=1
output-tensor-meta=1
network-type=0
parse-bbox-func-name=NvDsInferParseYoloFace
custom-lib-path=/app/engines/libnvdsparsebbox_Yolo_face.so
operate-on-class-ids=0
```

- [ ] **Step 2: Write `configs/sgie_arcface.txt`**

```ini
[property]
gpu-id=0
gie-unique-id=2
model-engine-file=/app/engines/arcface_r50_dynamic.onnx_b1_gpu0_fp16.engine
onnx-file=/app/models/arcface_r50_dynamic.onnx
batch-size=1
net-scale-factor=1.0
offsets=0.0;0.0;0.0
model-color-format=0
network-mode=2
process-mode=2
network-type=100
output-tensor-meta=1
input-object-min-width=20
input-object-min-height=20
operate-on-gie-id=1
operate-on-class-ids=0
```

- [ ] **Step 3: Create `configs/labels_face.txt`**

```text
face
```

---

## Task 6: Custom nvdspreprocess Alignment Plugin

**Files:**
- Create: `backend/src/pipeline/alignment/face_align.cpp`
- Create: `backend/src/pipeline/alignment/Makefile`

**Interfaces:**
- Produces: `/app/engines/libnvds_facealign.so` loaded by SGIE config if nvdspreprocess element is used.

- [ ] **Step 1: Implement 5-point similarity transform in CUDA/OpenCV**

Use `cv::estimateAffinePartial2D` on host or a small CUDA kernel; for Phase 1 a host implementation is acceptable because the number of faces per image is small. The plugin implements the `NvDsPreProcessCustomBatch` callback, reads `NvDsFaceMeta` if available, otherwise reads the 5 landmarks from `NvDsObjectMeta->mask_params` or an attached `NvDsUserMeta` produced by the custom YOLO face parser.

Because DeepStream does not have a built-in face landmark field in `NvDsObjectMeta`, the custom YOLO parser must attach landmark data as user meta. The alignment plugin reads that user meta, builds the affine matrix, and uses `nppiWarpAffine` or OpenCV CUDA `warpAffine` to produce the 112x112 tensor.

- [ ] **Step 2: Write the custom parser to emit landmarks as user meta**

The parser is based on `nvdsinfer_custom_impl_Yolo_face/nvdsparseface_Yolo.cpp`. Extend it so that after filling `NvDsObjectMeta`, it attaches an `NvDsUserMeta` containing the 5 landmarks in image coordinates.

- [ ] **Step 3: Build both `.so` files in container**

Run: `cd /app/backend/src/pipeline/alignment && make`
Expected: `libnvdsparsebbox_Yolo_face.so` and `libnvds_facealign.so` are copied to `/app/engines`.

---

## Task 7: DeepStream Python Pipeline Wrapper

**Files:**
- Create: `backend/src/pipeline/deepstream_pipeline.py`
- Create: `backend/src/pipeline/probe.py`

**Interfaces:**
- Consumes: image numpy array, PGIE/SGIE config paths.
- Produces: list of dicts with `bbox`, `confidence`, `embedding`.

- [ ] **Step 1: Create a single-image DeepStream pipeline**

For Phase 1, write a minimal pipeline:

```python
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import pyds


def run_on_image(image_path: str, pgie_config: str, sgie_config: str) -> list[dict]:
    Gst.init(None)
    pipeline = Gst.parse_launch(
        f"filesrc location={image_path} ! jpegdec ! videoconvert ! "
        f"video/x-raw,format=RGBA ! nvvideoconvert ! "
        f"video/x-raw(memory:NVMM),format=RGBA ! nvstreammux name=mux "
        f"! nvinfer config-file-path={pgie_config} "
        f"! nvinfer config-file-path={sgie_config} "
        f"! fakesink"
    )
    # Attach probe, set mux batch-size, run mainloop, collect results.
    ...
```

Use `nvstreammux` with `batch-size=1`, `width`, `height` from the original image.

- [ ] **Step 2: Attach probe after SGIE src pad**

```python
def sgie_src_pad_buffer_probe(pad, info, user_data):
    buf = info.get_buffer()
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    for frame_meta in pyds.NvDsFrameMetaList(batch_meta):
        for obj_meta in pyds.NvDsObjectMetaList(frame_meta.obj_meta_list):
            tensor_meta = ... # read classifier label/tensor
            embedding = ...
            user_data.append({
                "bbox": {...},
                "confidence": obj_meta.confidence,
                "embedding": embedding,
            })
    return Gst.PadProbeReturn.OK
```

- [ ] **Step 3: Add engine build guard**

On first container start, if `.engine` files are missing, DeepStream will generate them automatically from the `.onnx` paths. Ensure `/app/engines` is writable.

---

## Task 8: Recognition Matcher and Face ID Assignment

**Files:**
- Create: `backend/src/recognition/matcher.py`

**Interfaces:**
- Consumes: list of detections with embeddings; `GalleryService`.
- Produces: each detection annotated with `faceId`, `status`, `name`, `score`.

- [ ] **Step 1: Write matcher logic**

```python
from src.config import settings


class FaceMatcher:
    def __init__(self, gallery_service):
        self.gallery = gallery_service

    async def match_faces(self, detections: list[dict]) -> list[dict]:
        results = []
        for det in detections:
            hit = await self.gallery.find_match(det["embedding"], settings.recognition_threshold)
            if hit:
                face = await self.gallery.get_face(hit.id)
                det["faceId"] = hit.id
                det["status"] = face.status if face else "known"
                det["name"] = face.name if face and face.status == "known" else None
                det["score"] = float(hit.score)
            else:
                anon_hit = await self.gallery.find_match(det["embedding"], settings.anonymous_threshold)
                if anon_hit:
                    det["faceId"] = anon_hit.id
                    det["status"] = "anonymous"
                    det["name"] = None
                    det["score"] = float(anon_hit.score)
                else:
                    det["faceId"] = await self._create_anonymous(det["embedding"])
                    det["status"] = "new_anonymous"
                    det["name"] = None
                    det["score"] = 0.0
            results.append(det)
        return results

    async def _create_anonymous(self, embedding):
        face_id = uuid.uuid4().hex
        from src.db.models import FaceRecord
        self.gallery.db.add(FaceRecord(id=face_id, status="anonymous"))
        self.gallery.client.upsert(face_id, embedding, {"name": None})
        await self.gallery.db.commit()
        return face_id
```

---

## Task 9: Process Logging Service

**Files:**
- Create: `backend/src/process/service.py`

**Interfaces:**
- Consumes: request info and recognition results.
- Produces: persisted `ProcessLog` and `FaceAppearance` rows.

- [ ] **Step 1: Write logger service**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import ProcessLog, FaceAppearance


class ProcessLogger:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(self, task_type: str, detections: list[dict]) -> str:
        log = ProcessLog(task_type=task_type, face_count=len(detections))
        self.db.add(log)
        await self.db.flush()
        for det in detections:
            self.db.add(
                FaceAppearance(
                    face_id=det["faceId"],
                    process_id=log.id,
                    confidence=det["score"],
                    bounding_box=det["bbox"],
                )
            )
        await self.db.commit()
        return log.id

    async def get(self, process_id: str) -> ProcessLog | None:
        return await self.db.get(ProcessLog, process_id)
```

---

## Task 10: FastAPI Endpoints

**Files:**
- Create: `backend/src/api/router.py`
- Create: `backend/src/api/schemas.py`
- Modify: `backend/src/main.py`

**Interfaces:**
- Produces: REST endpoints defined in ProjectRequirements.md.

- [ ] **Step 1: Write schemas**

```python
from pydantic import BaseModel
from typing import Literal


class FaceResult(BaseModel):
    faceId: str
    status: Literal["known", "anonymous", "new_anonymous"]
    name: str | None
    boundingBox: dict
    confidence: float


class RecognizeResponse(BaseModel):
    processId: str
    faceCount: int
    faces: list[FaceResult]


class EnrollRequest(BaseModel):
    name: str
    metadata: dict | None = None
```

- [ ] **Step 2: Implement `/faces/recognize`**

```python
import uuid
import aiofiles
import cv2
from fastapi import APIRouter, UploadFile, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.session import get_db
from src.gallery.service import GalleryService
from src.pipeline.deepstream_pipeline import run_on_image
from src.process.service import ProcessLogger
from src.recognition.matcher import FaceMatcher
from src.api.schemas import RecognizeResponse, FaceResult

router = APIRouter()


@router.post("/faces/recognize", response_model=RecognizeResponse)
async def recognize(file: UploadFile, db: AsyncSession = Depends(get_db)):
    temp_path = f"/tmp/{uuid.uuid4().hex}.jpg"
    content = await file.read()
    async with aiofiles.open(temp_path, "wb") as f:
        await f.write(content)

    detections = run_on_image(temp_path, settings.pgie_config_path, settings.sgie_config_path)

    gallery = GalleryService(db)
    matcher = FaceMatcher(gallery)
    results = await matcher.match_faces(detections)

    logger = ProcessLogger(db)
    process_id = await logger.log("recognize", results)

    return RecognizeResponse(
        processId=process_id,
        faceCount=len(results),
        faces=[FaceResult(**r) for r in results],
    )
```

- [ ] **Step 3: Wire `backend/src/main.py`**

```python
from fastapi import FastAPI
from src.api.router import router

app = FastAPI(title="Mvision Face Recognition API")
app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## Task 11: Integration Tests

**Files:**
- Create: `backend/tests/test_recognize.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Add test**

```python
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_recognize_image():
    with open("/app/rachel.jpeg", "rb") as f:
        response = client.post("/api/v1/faces/recognize", files={"file": ("rachel.jpeg", f, "image/jpeg")})
    assert response.status_code == 200
    data = response.json()
    assert "processId" in data
    assert data["faceCount"] >= 1
    assert data["faces"][0]["faceId"]
    assert data["faces"][0]["status"] in ("known", "anonymous", "new_anonymous")
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest tests/test_recognize.py -v`
Expected: PASS after all prior tasks completed.

---

## Self-Review

**Spec coverage:**
- Image upload / validation: Task 10.
- Face detection + bounding boxes: Task 7.
- Face recognition + IDs + status: Task 8.
- Anonymous face storage: Task 8.
- Enroll/update/delete/query face: Task 8 / Task 10.
- Process ID + logging: Task 9 / Task 10.
- History / process query: Task 9, API endpoints need `GET` handlers added to Task 10.
- Docker deployment: Task 1.

**Gaps to add:**
- `GET /faces/{faceId}` and `GET /faces/{faceId}/history` endpoints.
- `GET /processes/{processId}` endpoint.
- `POST /faces/enroll` endpoint.
- MinIO image storage in `/faces/recognize`.

Add these as follow-up tasks before execution begins.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-phase1-gpu-hot-path.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach do you want?
