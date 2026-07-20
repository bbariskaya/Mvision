# Runtime & Artifact Inventory

Sprint 01 values were refreshed during the Sprint 02 Packet 1 preflight on 2026-07-20. Frozen
source models were not downloaded or modified. Generated TensorRT artifacts are ignored by Git.

## Host environment

| Item | Observed value | Notes |
|---|---|---|
| OS/architecture | Linux x86_64 | `uname -m` -> `x86_64` |
| API test Python | 3.12.13 | Observed in Sprint 01 API container |
| Docker | 29.1.5 | build `0e6fee6` |
| Docker Compose | v5.0.2 | Docker Compose plugin |
| Git | 2.43.0 | Active repository toolchain |
| `rg` (ripgrep) | **Not installed** | Using `git ls-files` / `find` fallback where needed |

## NVIDIA stack

| Item | Status | Notes |
|---|---|---|
| GPU | 3x Quadro RTX 8000, 49152 MiB each, compute capability 7.5 | `RUNTIME_VERIFIED` with `nvidia-smi` |
| Driver | 580.105.08 | Same on GPU 0, 1, and 2 |
| CUDA driver/runtime | 13.0 / 13.0 | Reported by `deepstream-app --version-all` |
| TensorRT | 10.16 | Reported by `deepstream-app --version-all` |
| DeepStream SDK | 9.0.0 | Installed host runtime |
| GStreamer | 1.24.2 | `gst-inspect-1.0 --version` |
| `nvjpegdec` | Installed | NVIDIA accelerated JPEG plugin; `image/jpeg` -> NVMM RGB |
| `nvstreammux` | Installed | DeepStream 9.0; CUDA-device memory and async processing available |
| `nvinfer` | Installed | DeepStream 9.0; host/device tensor metadata fields available |
| `nvdspreprocess` | Installed | DeepStream 9.0 official custom preprocess extension point |
| Host `nvcc` | Not on `PATH` | Native builds must use a pinned DeepStream devel container |
| Host `trtexec` | Not on `PATH` | Engine builds/benchmarks must run in the pinned container |

### Pinned native worker container

| Item | Observed value |
|---|---|
| DeepStream image | `nvcr.io/nvidia/deepstream:9.0-triton-multiarch@sha256:60888367d4c97ba192411a7694c984080a553f855ad53fc4c5579d70424fafd7` |
| TensorRT | 10.14.1.48 |
| CUDA toolkit/runtime | 13.1.115 / 13.1.80 |
| Compiler | GCC 13.3.0, CMake 3.19.6 |
| Target GPU | Quadro RTX 8000, SM 7.5 |

## Model artifacts present in repo

| Artifact | Path | SHA-256 | Verified contract |
|---|---|---|---|
| ArcFace R50 | `backend/models/arcface_r50_dynamic.onnx` | `ebbeb12e1162ff839e7c1ad3b6f63758198a001d9ad871b6e2f09256210995bf` | Input `[B,3,112,112]`; graph applies `(input-127.5)/128`; output `[B,512]` includes `LpNormalization` |
| YOLOv8n-Face | `backend/models/yolov8n-face.onnx` | `33f3951af7fc0c4d9b321b29cdcd8c9a59d0a29a8d4bdc01fcb5507d5c714809` | Input `[B,3,H,W]`; three 80-channel pose heads; metadata `kpt_shape=[5,3]`, stride 32 |

The deterministic inspector is `backend/scripts/inspect_model_contract.py`. Contract tests run in
the pinned `docker/model-inspector.Dockerfile` environment. Artifact presence, SHA, graph metadata,
shape inference, ArcFace constants, and `LpNormalization` are `SOURCE_VERIFIED`; TensorRT runtime
parity remains `NOT_PROVEN` until fixed-image oracle comparison.

## Generated TensorRT artifacts

Profile for both engines: dynamic batch `min=1`, `opt=64`, `max=256`, FP16 enabled.

| Artifact | SHA-256 | Size | Max activation memory |
|---|---|---:|---:|
| `backend/models/engines/yolov8n-face-sm75-trt10.14-fp16-b256.engine` | `db333a64b688441c2c1518f6836da9d1dc9f6c09319d3f6a6e5e24c569dadc60` | 7.5 MiB | 2.7 GB at batch 256 |
| `backend/models/engines/arcface-r50-sm75-trt10.14-fp16-b256.engine` | `3f63975200c57bbdf771005676e2ebd05243f531385c6cb7010b5d1a8517eb4d` | 85 MiB | 1.34 GB at batch 256 |

The frozen ArcFace artifact stores mean/std initializers as `[3]`, which is not conformable with
NCHW under standard ONNX broadcasting and is rejected by TensorRT. The deterministic generated
artifact `backend/models/generated/arcface_r50_tensorrt.onnx` changes only those initializer shapes
to `[1,3,1,1]`; its SHA-256 is
`0868301ba1449586da9fb4e9dcdd52f7c8e613443f02de07990d8f21bb2006c6`. Values and graph-owned
normalization remain unchanged.

### Single-GPU ceilings

Measured on GPU 0 with CUDA Graph and device-resident synthetic input (`--noDataTransfers`). These
are model-only ceilings, not end-to-end acceptance numbers.

| Stage | Batch | GPU latency | Images/faces per second |
|---|---:|---:|---:|
| GPU JPEG decode + NVMM mux ingress | 16 source slots | n/a | 1510.33 images/s |
| YOLOv8n-Face TensorRT | 64 | 21.39 ms | 2991.55 images/s |
| YOLOv8n-Face TensorRT | 256 | 82.47 ms | 3104.05 images/s |
| ArcFace R50 TensorRT | 64 | 13.51 ms | 4735.87 faces/s |
| ArcFace R50 TensorRT | 256 | 49.84 ms | 5136.51 faces/s |

## External services for Sprint 01 integration tests

| Service | Planned version/image | Port |
|---|---|---|
| PostgreSQL | `postgres:16-alpine` | 5432 |
| MinIO | `minio/minio:latest` | 9000 (API), 9001 (console) |
| Qdrant | `qdrant/qdrant:latest` | 6333 |

No live data migration or destructive repair is required for Sprint 01; tests run against isolated empty databases/volumes.
