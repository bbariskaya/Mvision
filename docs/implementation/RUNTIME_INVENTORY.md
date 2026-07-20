# Runtime & Artifact Inventory

Collected read-only during Sprint 01 preflight. No models were downloaded or modified.

## Host environment

| Item | Observed value | Notes |
|---|---|---|
| OS/architecture | Linux x86_64 (container/agent environment) | |
| Python | 3.x (to be verified at build time) | `python3` available |
| Docker | Available | `docker --version` to be run during acceptance |
| Docker Compose | Available | `docker compose version` to be run during acceptance |
| `rg` (ripgrep) | **Not installed** | Using `git ls-files` / `find` fallback where needed |

## NVIDIA stack

| Item | Status | Notes |
|---|---|---|
| GPU / driver | To be verified | `nvidia-smi` runtime check deferred to Sprint 02 acceptance |
| CUDA | To be verified | Sprint 01 does not build GPU code |
| TensorRT | To be verified | Sprint 02 gate |
| DeepStream | To be verified | Sprint 02 gate; official installed version wins |
| GStreamer | To be verified | Sprint 02 gate |

## Model artifacts present in repo

| Artifact | Path | SHA-256 | Status |
|---|---|---|---|---|
| ArcFace R50 (normalized) | `models/arcface_r50_dynamic.onnx` | TBD | Active Phase 1 model |
| ArcFace R50 (original backup) | `models/arcface_r50_dynamic.onnx.orig` | TBD | Backup before normalization |
| YOLOv8n-Face (dynamic) | `models/yolov8n-face.onnx` | TBD | Detector candidate for Sprint 02 |
| YOLOv8n-Face (lindevs static) | `models/yolov8n-face-lindevs.onnx` | TBD | Legacy/oracle; not used |

SHA-256 values will be recorded when the artifacts are formally inspected during Sprint 02 model-contract gate.

## External services for Sprint 01 integration tests

| Service | Planned version/image | Port |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | 5432 |
| MinIO | `minio/minio:latest` | 9000 (API), 9001 (console) |
| Qdrant | `qdrant/qdrant:latest` | 6333 |

No live data migration or destructive repair is required for Sprint 01; tests run against isolated empty databases/volumes.
