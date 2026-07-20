# Sprint 02 - DeepStream GPU Hot Path

## Objective

Deliver the real Phase 1 image identity vertical slice defined by
`requirements/ProjectRequirements.md`, using the approved YOLOv8-Face + ArcFace R50 models and a
persistent native DeepStream 9 data plane. Phase 1 must complete before any video implementation.

Detailed execution plan:
`docs/superpowers/plans/2026-07-20-phase1-deepstream-implementation.md`.

## Active Packet

Packet 2 / Tasks 3-4: persistent JPEG ingress and GPU detector postprocess.

Native protocol/build scaffolding and the persistent multi-slot GPU ingress are operational. The
current focus is fusing YOLO DFL decode/NMS/landmark compaction onto the GPU before nvinfer output
crosses the host boundary.

## Completed Packet

### Packet 1 - Runtime and Model Contract Gate

- [x] Frozen artifact SHA test written RED-first and verified GREEN.
- [x] Deterministic ONNX inspector implemented in a pinned Python 3.12 image.
- [x] YOLO contract verified: input `[B,3,H,W]`, three 80-channel pose heads,
  `kpt_shape=[5,3]`, stride 32.
- [x] ArcFace contract verified: input `[B,3,112,112]`, graph-owned
  `(input - 127.5) / 128`, output `[B,512]`, `LpNormalization` present.
- [x] Runtime recorded: 3x Quadro RTX 8000, driver 580.105.08, CUDA 13.0,
  TensorRT 10.16, DeepStream 9.0.0, GStreamer 1.24.2.
- [x] Upstream decisions refreshed from real source and commit hashes.
- [x] Internal implementation approval recorded; external/commercial model release remains a legal
  review gate.

## Packet 1 Evidence

```text
docker run ... pytest tests/contract/test_model_inventory.py -v
5 passed

docker compose ... ruff check app tests scripts
All checks passed

docker compose ... ruff format --check app tests scripts
51 files already formatted

docker compose ... mypy app tests scripts
Success: no issues found in 51 source files

make phase1-s1-acceptance
37 passed; migration 58ecca5e38a3 (head); git diff --check clean
```

Generated, uncommitted runtime report:
`/tmp/opencode/mvision-model-contract.json`.

### Packet 2 evidence so far

- Python MessagePack frame contract: `6 passed`.
- Native C++ protocol and real GPU ingress CTest: `2 passed`.
- Persistent 16-slot `appsrc -> nvjpegdec -> NVMM -> nvstreammux` ingress: `1510.33 images/s` on
  one RTX 8000.
- YOLO FP16 dynamic engine, batch 1/64/256: built and benchmarked at `3104.05 images/s` ceiling for
  batch 256 on one RTX 8000.
- ArcFace FP16 dynamic engine, batch 1/64/256: built and benchmarked at `5136.51 faces/s` ceiling for
  batch 256 on one RTX 8000.

## Deliverables Remaining

- Native C++17 worker process and Python/C++ protocol parity.
- Request correlation across source slots and output batches.
- GPU DFL decode/NMS/five-landmark compaction fused into the YOLO TensorRT engine.
- Standard instance-mask landmark transport.
- Official `nvdspreprocess` CUDA/NPP five-point alignment.
- ArcFace SGIE and compact normalized embedding extraction.
- GPU-only aligned JPEG evidence encoding.
- Python GPU scheduler and full identity/storage lifecycle.
- Recognition, enrollment, identity/sample, history, and process APIs.
- Docker Compose deployment, restart acceptance, and measured throughput.

## Non-Goals

- Video upload, video jobs, sampling, tracking, or aggregation.
- RTSP, webcam, live stream, camera lifecycle, or alerts.
- UI.
- Public bulk/dataset management API.
- RetinaFace, GlintR100, SCRFD, or a second embedding space.
- CPU decode/inference/postprocess/alignment/encoding fallback.
- DeepStream Python bindings or patched system DeepStream libraries.
- Model/dataset download, driver/system CUDA changes, or old collection reset.
- Git commit/push without explicit user request.

## Hard Stops

- Active root/branch changes unexpectedly or user changes overlap target files.
- Frozen model SHA/tensor contract changes.
- Pinned DeepStream 9 devel image is unavailable or incompatible with driver 580.105.08.
- Standard DeepStream metadata cannot carry landmarks into official `nvdspreprocess`.
- Standard ArcFace SGIE cannot consume preprocess tensor meta without patched `nvinfer`.
- GPU-native JPEG ingress/alignment/evidence encode cannot be runtime-verified.
- A model/system dependency download or destructive storage action becomes necessary.

## Evidence Classification

- `SOURCE_VERIFIED`: model graph, hashes, current code, configs, and upstream source observed.
- `RUNTIME_VERIFIED`: host NVIDIA runtime and Sprint 01 real dependency tests executed.
- `NOT_PROVEN`: native worker, engine inference, GPU-only boundary, identity vertical slice,
  throughput, three-GPU scaling.
- `RELEASE_BLOCKED_LEGAL_REVIEW`: active model artifacts approved for internal implementation,
  not approved here for external/commercial distribution.
