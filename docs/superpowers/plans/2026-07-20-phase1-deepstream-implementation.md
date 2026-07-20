# Phase 1 DeepStream Face Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Do not implement video or live streaming. Do not commit
> unless the user explicitly requests a commit.

**Goal:** Implement every behavior in `requirements/ProjectRequirements.md` with a persistent,
three-GPU NVIDIA DeepStream 9.0 data plane and the existing FastAPI/PostgreSQL/MinIO/Qdrant
foundation.

**Architecture:** FastAPI remains the control plane and business owner. Three long-lived native
C++ DeepStream workers, one per Quadro RTX 8000, process encoded JPEGs through GPU decode,
YOLOv8-Face, fused GPU decode/NMS/landmarks, `nvdspreprocess` five-point alignment, ArcFace R50,
and GPU evidence encoding. Python receives only compact metadata, normalized embeddings, and
aligned JPEG bytes, then executes identity lifecycle and durable cross-store writes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL 16, MinIO, Qdrant,
NVIDIA DeepStream 9.0, GStreamer, CUDA 13.0, TensorRT 10.16, NPP/nvJPEG, C++17, CMake, Docker
Compose.

**Authoritative design:**
`docs/superpowers/specs/2026-07-20-phase1-deepstream-design.md`.

**Supersedes:** `docs/superpowers/plans/2026-07-20-phase1-gpu-hot-path.md`. The superseded plan
uses DeepStream 7.1, deprecated Python bindings, per-request pipelines, CPU OpenCV, and an
incompatible database design; it must not be executed.

## Global Constraints

- Phase 1 implements `requirements/ProjectRequirements.md`; video/live code is forbidden.
- Preserve Presentation -> Service -> Infrastructure and the five canonical PostgreSQL tables.
- Use DeepStream 9.0 native C++; do not use production PyDS/Python pipeline bindings.
- Never patch or replace installed DeepStream `.so` files.
- Use persistent workers; never construct a GStreamer pipeline per request.
- Production input format is JPEG. Reject unsupported formats without CPU fallback.
- Keep decoded images, detector tensors, aligned tensors, and unnormalized embeddings on GPU.
- CPU output is limited to compact metadata, normalized 512-D embeddings, and GPU-encoded JPEG.
- ArcFace artifact preprocessing is `(input - 127.5) / 128`; its graph already applies
  `LpNormalization`. Do not normalize pixels or output a second incompatible way.
- MinIO key is `faces/{faceId}/{sampleId}/aligned`, content type `image/jpeg`.
- Qdrant point ID equals `sampleId`; PostgreSQL remains lifecycle source of truth.
- Use one calibrated recognition threshold. Status comes from PostgreSQL identity state, not a
  second anonymous threshold.
- Every enrollment/sample image must contain exactly one face.
- No hard-coded `256` batch assumption. Select batch/profile sizes from measured sweeps.
- No model/engine download, system package change, migration rewrite, destructive data action,
  or Git commit without explicit user authorization.
- Every GPU PASS requires real-runtime evidence; mocks, skips, build success, and engine load are
  insufficient.

## Upstream Source Findings

The implementation agent must use these as bounded references, not copy entire repositories:

| Reference | Verified implementation | Decision |
|---|---|---|
| `marcoslucianops/DeepStream-Yolo-Face@b46e259` (MIT) | `config_infer_primary_yoloV8_face.txt` uses `network-type=3`, `parse-bbox-instance-mask-func-name`, and `output-instance-mask=1`; `addFaceProposal()` places five `(x,y,visibility)` landmarks in `NvDsInferInstanceMaskInfo.mask`; `main()` demonstrates CUDA-device `nvstreammux` and explicit `PLAYING -> NULL` teardown. Its parser performs host NMS and one allocation per proposal. | ADAPT standard mask transport/config and lifecycle; reject host NMS/per-proposal allocation. |
| `zhouyuchong/face-recognition-deepstream@d18cc58` (MIT) | Pipeline is `streammux -> PGIE -> tracker -> SGIE`; config uses patched `enable-output-landmark`, `network-type=100`, and `alignment-type=1`. `get_face_feature()` copies 512 values one-by-one to Python, normalizes with NumPy, then uses hard-coded cosine `0.3`. | ORACLE for stage ordering only; reject PyDS data plane, patch-only properties, CPU normalization/search, and threshold. |
| `zhouyuchong/gst-nvinfer-custom@4ca3fc7` (no repository license found) | Computes Umeyama matrix with OpenCV/SVD on CPU, allocates CUDA buffers inside processing, warps with `nppiWarpAffine_8u_C3R`, optionally copies crops to host, and replaces system DeepStream libraries. | ORACLE_ONLY for ArcFace template/transform direction and NPP parity; never copy, install, or patch. |
| `yakhyo/yolov8-face-onnx-inference@33f893f` (no repository license endpoint found) | `postprocess()` documents the active three-head layout: 64 DFL + 1 class + 15 keypoint channels, strides 8/16/32, 0.5 bbox grid, integer keypoint grid, sigmoid class, and NMS. Implementation is NumPy/TorchVision/OpenCV. | ORACLE_ONLY for frozen decode fixtures; reimplement independently in CUDA. |
| `lindevs/yolov8-face@c6a3dee` | Provides detector-only pretrained models and dynamic export, but its documented model is not the active five-landmark artifact. | Do not substitute its weights/model for the active artifact. |
| `NNDam/deepstream-face-recognition` | Custom `batchedNMSDynamic_TRT` carries landmarks, but upstream reports batch-size correctness problems and GPU alignment remains TODO. | Risk evidence only; do not adopt plugin source. |
| `Abdirayimov/multi-stream-face-recognition` (MIT) | C++17 persistent DeepStream architecture, batched ArcFace, probe chain, source lifecycle, and benchmark/enrollment tools. | Architecture reference for later multi-stream work; Phase 1 still proves its own exact image ingress/runtime. |
| NVIDIA DeepStream official apps/docs | Verify source bins, request pads, `nvstreammux`, CUDA-device memory, tensor meta, bus handling, and teardown. Official samples batch across source pads; they do not prove reusable `appsrc -> nvjpegdec` request slots. | ADOPT official APIs; keep Task 3 ingress reproducer as a hard gate. |

No inspected upstream provides all of: persistent HTTP image request correlation, GPU DFL/NMS,
unpatched landmark alignment, GPU ArcFace extraction, GPU JPEG evidence, and durable identity
lifecycle. The production path is therefore an integration of verified standard interfaces, not a
fork of one demo.

## File Structure

### Native data plane

- `backend/pipeline/CMakeLists.txt` - native build and test targets.
- `backend/pipeline/include/mvision/model_contract.hpp` - frozen model tensor contract.
- `backend/pipeline/include/mvision/protocol.hpp` - framed worker request/result DTOs.
- `backend/pipeline/include/mvision/pipeline.hpp` - persistent pipeline public API.
- `backend/pipeline/src/worker_main.cpp` - one-GPU daemon entry point.
- `backend/pipeline/src/pipeline.cpp` - GStreamer graph, lifecycle, bus, and request completion.
- `backend/pipeline/src/image_source_pool.cpp` - persistent `appsrc -> nvjpegdec` source slots.
- `backend/pipeline/src/result_collector.cpp` - compact tensor/meta extraction and correlation.
- `backend/pipeline/src/aligned_jpeg_encoder.cpp` - GPU-only aligned JPEG evidence encoding.
- `backend/pipeline/plugins/yolo_face_decode/` - TensorRT GPU decode/NMS plugin.
- `backend/pipeline/nvdsinfer_custom_impl_Yolo/nvdsparse_yolo_face.cpp` - compact final-output
  parser and landmark metadata attachment.
- `backend/pipeline/nvdspreprocess_align/` - official custom preprocess library for GPU alignment.
- `backend/pipeline/tests/` - native unit, contract, runtime, and teardown tests.

### DeepStream configuration and artifacts

- `configs/pgie_yolov8_face.txt` - detector `nvinfer` config.
- `configs/preprocess_arcface.txt` - object-mode landmark alignment config.
- `configs/sgie_arcface_r50.txt` - ArcFace input-tensor-meta config.
- `backend/scripts/inspect_model_contract.py` - ONNX contract/hash report.
- `backend/scripts/build_engines.sh` - reproducible TensorRT/plugin engine build.
- `backend/models/` - existing ONNX inputs; generated engines remain Git-ignored.
- `docker/model-inspector.Dockerfile` - pinned, CPU-only ONNX inspection environment.

### Python control plane

- `backend/app/infrastructure/gpu/contracts.py` - typed compact worker DTOs.
- `backend/app/infrastructure/gpu/worker_client.py` - framed Unix-socket client.
- `backend/app/infrastructure/gpu/scheduler.py` - bounded least-loaded three-worker scheduling.
- `backend/app/services/recognition_service.py` - process, match, anonymous creation, results.
- `backend/app/services/enrollment_service.py` - exact-one-face enrollment and promotion.
- `backend/app/services/identity_service.py` - identity/sample query, update, delete, history.
- `backend/app/services/face_sample_persistence_service.py` - sample-only cross-store lifecycle.
- `backend/app/presentation/process_context.py` - UUIDv7 request/process correlation.
- `backend/app/presentation/schemas/` - recognition, enrollment, identity, process schemas.
- `backend/app/presentation/controllers/` - request/service/response mapping.
- `backend/app/presentation/routers/face_router.py` - face and sample endpoints.
- `backend/app/presentation/routers/process_router.py` - process detail endpoint.
- `backend/app/internal/bulk_enroll.py` - non-public labeled-directory utility.

### Verification and deployment

- `backend/tests/contract/` - model, schema, and worker-protocol tests.
- `backend/tests/integration/gpu/` - real DeepStream/TensorRT tests.
- `backend/tests/integration/api/` - real API and dependency acceptance.
- `backend/tests/integration/services/` - lifecycle and cross-store failure tests.
- `docker/deepstream-worker.Dockerfile` - pinned DeepStream 9.0 worker image.
- `backend/Dockerfile` - API image only.
- `docker-compose.yml` - API, three GPU workers, PostgreSQL, MinIO, Qdrant.
- `Makefile` - packet-specific and final acceptance gates.

---

## Packet 1: Runtime and Model Contract Gate

### Task 1: Freeze runtime, artifacts, and legal gates

**Files:**
- Modify: `docs/implementation/RUNTIME_INVENTORY.md`
- Modify: `docs/implementation/REFERENCE_DECISION_LOG.md`
- Create: `backend/scripts/inspect_model_contract.py`
- Create: `docker/model-inspector.Dockerfile`
- Test: `backend/tests/contract/test_model_inventory.py`

**Interfaces:**
- Consumes: `backend/models/yolov8n-face.onnx`,
  `backend/models/arcface_r50_dynamic.onnx`.
- Produces: machine-readable `backend/models/model-contract.json` during validation; the generated
  report is not committed.

- [ ] **Step 1 of 60: Write the failing artifact inventory test**

  Assert the exact current files and hashes before any engine work:

  ```python
  EXPECTED = {
      "yolov8n-face.onnx":
          "33f3951af7fc0c4d9b321b29cdcd8c9a59d0a29a8d4bdc01fcb5507d5c714809",
      "arcface_r50_dynamic.onnx":
          "ebbeb12e1162ff839e7c1ad3b6f63758198a001d9ad871b6e2f09256210995bf",
  }
  ```

  Test failure must identify a missing or changed artifact, not regenerate/download it.

- [ ] **Step 2 of 60: Implement deterministic ONNX inspection**

  Create the inspection image exactly as:

  ```dockerfile
  FROM python:3.12-slim
  RUN pip install --no-cache-dir onnx==1.22.0
  WORKDIR /work
  ```

  `inspect_model_contract.py` must load ONNX without modifying it and emit JSON containing SHA,
  metadata, inputs, outputs, dtypes, symbolic dimensions, operator set, and small initializer
  values. Assert these observed contracts:

  ```text
  YOLO input: images [batch,3,height,width]
  YOLO outputs: output0, 442, 450; each 80 channels after shape inference
  YOLO metadata: task=pose, kpt_shape=[5,3], stride=32, license=AGPL-3.0
  ArcFace input: input.1 [batch,3,112,112]
  ArcFace constants: mean=[127.5,127.5,127.5], std=[128,128,128]
  ArcFace output: output [batch,512], graph contains LpNormalization
  ```

- [ ] **Step 3 of 60: Record installed runtime from exact commands**

  Run and copy raw summaries into `RUNTIME_INVENTORY.md`:

  ```bash
  nvidia-smi
  deepstream-app --version-all
  gst-inspect-1.0 nvjpegdec
  gst-inspect-1.0 nvstreammux
  gst-inspect-1.0 nvinfer
  gst-inspect-1.0 nvdspreprocess
  ```

  Expected baseline: 3x Quadro RTX 8000 49152 MiB, driver `580.105.08`, CUDA `13.0`, DeepStream
  `9.0.0`, TensorRT `10.16`. A mismatch blocks engine serialization until documented.

- [ ] **Step 4 of 60: Freeze model provenance and stop conditions**

  Add an `ADOPT/ADAPT/ORACLE_ONLY` decision for each upstream. YOLO production use remains
  blocked until the user accepts its model/weight AGPL/provenance implications. ArcFace remains
  blocked until pretrained-weight usage terms are accepted. No source from an unlicensed repo is
  copied into production.

- [ ] **Step 5 of 60: Run Packet 1 gate**

  ```bash
  docker build -f docker/model-inspector.Dockerfile -t mvision-model-inspector:local .
  docker run --rm -v "$PWD/backend:/work:ro" mvision-model-inspector:local \
    python /work/scripts/inspect_model_contract.py
  docker compose -f docker-compose.sprint01.yml run --rm api \
    pytest tests/contract/test_model_inventory.py -v
  git diff --check
  ```

  Expected: contract test PASS, generated report agrees with both SHA values, no artifact changed.
  Stop with `BLOCKED_NEEDS_USER_DECISION` if license/provenance is not approved.

### Task 2: Establish native worker build and typed protocol

**Files:**
- Create: `backend/pipeline/CMakeLists.txt`
- Create: `backend/pipeline/include/mvision/model_contract.hpp`
- Create: `backend/pipeline/include/mvision/protocol.hpp`
- Create: `backend/pipeline/src/worker_main.cpp`
- Create: `backend/pipeline/tests/test_protocol.cpp`
- Create: `backend/tests/contract/test_worker_protocol.py`

**Interfaces:**
- Consumes: frozen values from Task 1.
- Produces:
  `mvision-worker --gpu-id N --socket /run/mvision/gpu-N.sock` and a versioned MessagePack
  length-prefixed protocol shared by C++ and Python.

- [ ] **Step 6 of 60: Define cross-language request/result schemas in failing tests**

  Freeze protocol version `1` and these logical DTOs:

  ```cpp
  struct ImageRequest {
    std::string request_id;
    std::vector<std::uint8_t> encoded_jpeg;
  };
  struct FaceOutput {
    std::uint32_t ordinal;
    float x, y, width, height;
    std::array<float, 10> landmarks_xy;
    float detector_confidence;
    std::array<float, 512> embedding;
    std::vector<std::uint8_t> aligned_jpeg;
  };
  struct ImageResult {
    std::string request_id;
    std::string status;
    std::string error_code;
    std::vector<FaceOutput> faces;
  };
  ```

  Python and C++ round-trip fixtures must produce byte-identical decoded field values.

- [ ] **Step 7 of 60: Implement bounded framed transport**

  Use `uint32_be payload_length + MessagePack payload` over Unix domain `SOCK_STREAM`. Reject
  frames larger than `max_upload_bytes + 16 MiB`, unknown protocol versions, duplicate
  `request_id`, non-JPEG payloads, and truncated frames. Do not Base64 image/evidence bytes.

- [ ] **Step 8 of 60: Add native process lifecycle contract**

  `worker_main.cpp` must parse config, call `cudaSetDevice(gpu_id)` before GPU resource creation,
  create the socket with mode `0660`, start one persistent pipeline, handle SIGTERM through a
  bounded drain, call idempotent `Pipeline::close()`, unlink its own socket, and exit `0`.

- [ ] **Step 9 of 60: Build the minimal worker in a pinned DeepStream devel container**

  CMake must use C++17 and explicitly link GStreamer, DeepStream metadata/infer libraries, CUDA,
  TensorRT, NPP, nvJPEG, pthread, and MessagePack. No host-global installation is allowed.

  ```bash
  cmake -S backend/pipeline -B build/pipeline -DCMAKE_BUILD_TYPE=RelWithDebInfo
  cmake --build build/pipeline --parallel
  ctest --test-dir build/pipeline --output-on-failure
  ```

- [ ] **Step 10 of 60: Run protocol and teardown gate**

  Start the skeleton worker, send malformed and valid framed messages from Python, issue SIGTERM
  three times in separate runs, and assert bounded exit, no stale socket, no crash, and protocol
  error responses contain no local paths or stack traces.

## Packet 2: Persistent DeepStream Detector

### Task 3: Prove persistent JPEG ingress and request correlation

**Files:**
- Create: `backend/pipeline/include/mvision/pipeline.hpp`
- Create: `backend/pipeline/src/pipeline.cpp`
- Create: `backend/pipeline/src/image_source_pool.cpp`
- Create: `backend/pipeline/tests/test_image_ingress.cpp`
- Create: `backend/tests/integration/gpu/test_image_ingress.py`

**Interfaces:**
- Consumes: `ImageRequest` from Task 2.
- Produces: one NVMM frame carrying a stable `(source_id, pts_token)` correlation key per input.

- [ ] **Step 11 of 60: Write real-runtime ingress failures first**

  Tests send valid JPEG, empty bytes, corrupt JPEG, PNG mislabeled as JPEG, and two concurrent
  JPEGs. Expected valid result is one NVMM frame with matching token; invalid inputs return
  `EMPTY_IMAGE`, `CORRUPT_IMAGE`, or `UNSUPPORTED_MEDIA_TYPE` without poisoning the next request.

- [ ] **Step 12 of 60: Build a persistent source-slot pool**

  Create configurable slots, each:

  ```text
  appsrc caps=image/jpeg format=time is-live=false
    -> queue max-size-buffers=2 leaky=no
    -> nvjpegdec gpu-id=N
    -> nvvideoconvert
    -> video/x-raw(memory:NVMM),format=RGBA
    -> nvstreammux.sink_K
  ```

  Never EOS a slot per request. Push one encoded buffer with a unique monotonically increasing
  PTS token and recycle the slot only after completion/failure.

  This exact reusable-slot pattern is not proven by the inspected upstreams. First implement it as
  a standalone DeepStream 9 reproducer and require two sequential images per slot plus concurrent
  slots to pass before integrating detector code. If `nvjpegdec` cannot safely decode repeated
  appsrc JPEG buffers, stop at `BLOCKED_IMAGE_INGRESS_CONTRACT`; do not replace it with CPU decode.

- [ ] **Step 13 of 60: Configure GPU-resident muxing**

  Set `nvstreammux` width/height `640x640`, `enable-padding=true`, `compute-hw=GPU`,
  `nvbuf-memory-type=nvbuf-mem-cuda-device`, `live-source=false`, `async-process=true`, measured
  `batch-size`, and bounded `batched-push-timeout`. Record original width/height and letterbox
  scale/padding in frame user metadata for reverse mapping.

- [ ] **Step 14 of 60: Implement correlation and per-input failure isolation**

  Index in-flight requests by `(source_id, pts_token)`. Read `NvDsFrameMeta.source_id` and
  `buf_pts` after mux. A decoder error completes only its owning request unless GStreamer reports
  a systemic pipeline/CUDA failure; systemic failure fails all in-flight requests and restarts
  the worker process rather than silently rebuilding in-request.

- [ ] **Step 15 of 60: Benchmark ingress batch sweep**

  Run source-slot/mux sweeps `1, 8, 16, 32, 64, 128`; include `256` only if memory and stability
  permit. Measure decode FPS, p50/p95 queue wait, GPU memory, and error rate. Freeze the best
  sustainable bulk value and a bounded interactive timeout in evidence, not source constants.

### Task 4: Implement TensorRT GPU decode, NMS, and landmark outputs

**Files:**
- Create: `backend/pipeline/plugins/yolo_face_decode/CMakeLists.txt`
- Create: `backend/pipeline/plugins/yolo_face_decode/yolo_face_decode_plugin.hpp`
- Create: `backend/pipeline/plugins/yolo_face_decode/yolo_face_decode_plugin.cpp`
- Create: `backend/pipeline/plugins/yolo_face_decode/yolo_face_decode_kernel.cu`
- Create: `backend/pipeline/plugins/yolo_face_decode/test_yolo_face_decode.cu`
- Create: `backend/scripts/build_engines.sh`

**Interfaces:**
- Consumes: three YOLO tensors `[B,80,80,80]`, `[B,80,40,40]`, `[B,80,20,20]` at 640 input.
- Produces fixed compact tensors: `num_dets [B]`, `boxes [B,MAX,4]`, `scores [B,MAX]`,
  `landmarks [B,MAX,5,2]` in network coordinates.

- [ ] **Step 16 of 60: Create a CPU oracle test without putting CPU code in production**

  Use the read-only upstream `tmp/yolov8-face-onnx/models/yolov8.py` only as an oracle fixture.
  Freeze expected outputs for no-face, one-face, and synthetic-overlap tensors. Do not import
  NumPy/OpenCV oracle code in production or copy unlicensed source.

- [ ] **Step 17 of 60: Implement exact CUDA decode**

  For strides `8,16,32`, decode channels exactly as the inspected artifact requires:

  ```text
  0..63   = four 16-bin DFL logits; softmax and expectation 0..15
  64      = class logit; sigmoid
  65..79  = five (x,y,visibility) keypoints
  bbox    = (grid + 0.5 +/- DFL distance) * stride
  kpt xy  = (raw * 2 + integer grid) * stride
  ```

  Filter non-finite values and confidence below configured detector threshold on device.

- [ ] **Step 18 of 60: Implement deterministic GPU NMS and bounds**

  Sort candidates by score with deterministic tie-breaking, apply IoU NMS on device, clamp to
  network bounds, preserve associated landmarks, and cap `MAX_DETECTIONS` only after NMS. If the
  configured cap could truncate a real acceptance image, fail the gate rather than silently
  truncate requirement-visible faces.

- [ ] **Step 19 of 60: Register and serialize the TensorRT plugin**

  Implement TensorRT 10 dynamic-shape plugin methods, workspace sizing, format support
  (`FP16` input, `FP32` compact output), clone/serialize/deserialize, namespace, and enqueue on
  TensorRT's provided CUDA stream. No default-stream synchronization or host postprocess.

- [ ] **Step 20 of 60: Build engines and prove parity**

  `build_engines.sh` must run in the pinned worker image, use explicit min/opt/max profiles from
  Task 3 measurements, save build logs and SHA-256, and refuse runtime auto-build. Compare plugin
  output against oracle fixtures and real no-face/one-face/multi-face images for batch 1 and
  batch N within declared coordinate/score tolerance.

### Task 5: Attach compact detections and restore original coordinates

**Files:**
- Create: `backend/pipeline/nvdsinfer_custom_impl_Yolo/CMakeLists.txt`
- Create: `backend/pipeline/nvdsinfer_custom_impl_Yolo/nvdsparse_yolo_face.cpp`
- Create: `backend/pipeline/tests/test_yolo_face_parser.cpp`
- Create: `configs/pgie_yolov8_face.txt`

**Interfaces:**
- Consumes: compact plugin outputs from Task 4 and frame letterbox metadata from Task 3.
- Produces: one `NvDsObjectMeta` per face with bbox, score, and five landmarks in
  `NvDsInferInstanceMaskInfo.mask`/`NvOSD_MaskParams` compatible metadata.

- [ ] **Step 21 of 60: Write parser contract tests**

  Feed compact tensors for zero, one, and multiple detections. Assert object count, class `0`,
  confidence, deterministic order, 15-float landmark mask layout
  `(x,y,visibility) * 5`, mask byte size, and no proposal-level memory leak across 10,000 calls.

- [ ] **Step 22 of 60: Implement compact-only parser**

  Export the exact symbol:

  ```cpp
  extern "C" bool NvDsInferParseCustomYoloFace(
      const std::vector<NvDsInferLayerInfo>& layers,
      const NvDsInferNetworkInfo& network,
      const NvDsInferParseDetectionParams& params,
      std::vector<NvDsInferInstanceMaskInfo>& objects);
  ```

  Read only `num_dets`, `boxes`, `scores`, and `landmarks`; never copy raw 80-channel tensors or
  run host NMS.

- [ ] **Step 23 of 60: Configure standard DeepStream instance-mask transport**

  `pgie_yolov8_face.txt` must set `process-mode=1`, `network-type=3`, `cluster-mode=4`,
  `output-instance-mask=1`, `parse-bbox-instance-mask-func-name=NvDsInferParseCustomYoloFace`,
  custom library/plugin paths, FP16, measured batch size, and `maintain-aspect-ratio=1`. Do not
  use patched `enable-output-landmark` or replace `libnvdsgst_infer.so`.

- [ ] **Step 24 of 60: Restore original image coordinates once**

  Apply inverse letterbox using recorded scale and pad:

  ```text
  x_original = clamp((x_network - pad_x) / scale, 0, original_width)
  y_original = clamp((y_network - pad_y) / scale, 0, original_height)
  ```

  Apply the same transform to all five landmarks. Store bbox as `x,y,width,height`; use original
  coordinates in API metadata while preserving network coordinates only inside GPU alignment.

- [ ] **Step 25 of 60: Run detector acceptance**

  Execute real DeepStream batches containing no-face, one-face, multi-face, portrait, landscape,
  and padded images. Compare original-coordinate outputs against the approved oracle; assert no
  missing face due to cap, no negative/out-of-bounds coordinate, and batch-1/batch-N parity.

## Packet 3: GPU Alignment, ArcFace, and Evidence

### Task 6: Implement official `nvdspreprocess` five-point GPU alignment

**Files:**
- Create: `backend/pipeline/nvdspreprocess_align/CMakeLists.txt`
- Create: `backend/pipeline/nvdspreprocess_align/face_align.hpp`
- Create: `backend/pipeline/nvdspreprocess_align/face_align.cpp`
- Create: `backend/pipeline/nvdspreprocess_align/face_align_kernel.cu`
- Create: `backend/pipeline/nvdspreprocess_align/custom_preprocess.cpp`
- Create: `backend/pipeline/tests/test_face_alignment.cu`
- Create: `configs/preprocess_arcface.txt`

**Interfaces:**
- Consumes: face ROI plus five network-coordinate landmarks from object mask metadata.
- Produces: batched `[N,3,112,112]` FP32 RGB tensors containing raw `0..255` values and retained
  aligned RGB8 device buffers for evidence encoding.

- [ ] **Step 26 of 60: Freeze alignment parity fixtures**

  Use this ArcFace destination template exactly:

  ```cpp
  constexpr float kTemplate[10] = {
      38.2946F, 51.6963F, 73.5318F, 51.5014F, 56.0252F,
      71.7366F, 41.5493F, 92.3655F, 70.7299F, 92.2041F};
  ```

  Generate approved fixture matrices/crops with InsightFace as `ORACLE_ONLY`; tests compare GPU
  landmarks and pixels within explicit tolerances and include rotation, scale, translation, and
  near-degenerate landmarks.

- [ ] **Step 27 of 60: Implement batched similarity transforms on CUDA**

  For each face compute centered source/destination points and the closed-form 2D Procrustes
  coefficients (`a = sum dot`, `b = sum cross`, denominator = source squared norm). Produce one
  source-to-destination `2x3` matrix per face. Reject non-finite or denominator-below-epsilon
  landmarks with `INVALID_LANDMARKS`; do not fall back to bbox crop.

- [ ] **Step 28 of 60: Warp canonical RGB8 faces on device**

  Use NPP/CUDA on the same worker stream to generate exactly `112x112` RGB8 aligned buffers.
  Define interpolation, border fill, pixel-center, ROI, and transform direction in one constant
  contract. Then launch an HWC-uint8 to NCHW-FP32 kernel without applying mean/std, because the
  ArcFace ONNX graph owns normalization.

- [ ] **Step 29 of 60: Implement official custom preprocess callbacks**

  Export DeepStream 9 `CustomTransformation`/`CustomTensorPreparation` callbacks with matching
  installed headers. Configure object mode (`process-on-frame=0`), `operate-on-gie-id=1`, target
  SGIE ID `2`, network order NCHW, FP32, and measured max batch. Read landmarks from standard
  object mask metadata and attach retained aligned-buffer ownership to batch user metadata with
  explicit copy/release callbacks.

  Before writing warp code, add a DeepStream 9 metadata reproducer proving that PGIE
  `NvOSD_MaskParams` remains reachable from each `NvDsPreProcessUnit`/ROI object. The older patched
  repo is not evidence for the official custom-library path. Failure is
  `BLOCKED_LANDMARK_PREPROCESS_META`, not permission to patch `nvinfer`.

- [ ] **Step 30 of 60: Prove alignment safety and teardown**

  Run parity fixtures at batch `1, 2, 16` and measured max; use compute-sanitizer for out-of-bounds,
  leak, race, and invalid access checks. Repeatedly construct/close preprocess resources and
  assert retained buffers are freed after downstream completion, not before SGIE/evidence use.

### Task 7: Run ArcFace and encode canonical evidence on GPU

**Files:**
- Create: `configs/sgie_arcface_r50.txt`
- Create: `backend/pipeline/src/result_collector.cpp`
- Create: `backend/pipeline/src/aligned_jpeg_encoder.cpp`
- Create: `backend/pipeline/tests/test_result_collector.cpp`
- Create: `backend/tests/integration/gpu/test_arcface_evidence.py`

**Interfaces:**
- Consumes: aligned FP32 tensor meta and retained RGB8 device buffer from Task 6.
- Produces: compact `FaceOutput` with original bbox/landmarks, detector score, normalized 512-D
  embedding, and `image/jpeg` aligned evidence.

- [ ] **Step 31 of 60: Write embedding/evidence failures first**

  Assert each accepted face produces exactly 512 finite floats, L2 norm `1.0 +/- 1e-5`, JPEG
  magic bytes `FFD8`, decoded dimensions `112x112`, and a SHA-stable evidence object for a fixed
  runtime/engine. Reject all-zero/non-finite embedding and failed GPU encoding.

- [ ] **Step 32 of 60: Configure standard ArcFace SGIE**

  Use `process-mode=2`, `gie-unique-id=2`, `operate-on-gie-id=1`, `input-tensor-meta=1`,
  `output-tensor-meta=1`, FP16 engine, measured batch size, and standard classifier mode only to
  schedule inference. Suppress classifier labels; consume tensor metadata. Do not use patched
  `network-type=100`, offsets, or net-scale preprocessing that duplicates the ONNX graph.

  Prove first with a minimal DeepStream 9 reproducer that standard `network-type=1` accepts the
  custom preprocess tensor, emits one `[N,512]` tensor meta associated with the correct objects,
  and exposes the expected `out_buf_ptrs_dev`. If this contract fails, stop with
  `BLOCKED_STANDARD_ARCFACE_SGIE`; do not import the patched `network-type=100` implementation.

- [ ] **Step 33 of 60: Extract normalized embeddings from device output**

  In the SGIE src-pad native probe, locate tensor meta for GIE ID `2`, validate output name and
  shape `[N,512]`, enqueue only the compact device-to-pinned-host copy on the pipeline stream,
  and verify norm/finite values after synchronization. Correlate each tensor row to object and
  request ordinal without a Python list/NumPy intermediate.

- [ ] **Step 34 of 60: Encode the exact aligned RGB8 buffer with nvJPEG**

  Use nvJPEG GPU encoder state per worker and batched encode where available. Configure fixed
  JPEG quality/chroma parameters through environment-backed worker config. Retrieve only final
  compressed bitstream bytes to host. No libjpeg/OpenCV/Pillow fallback is permitted; encoding
  failure fails sample creation with `GPU_ENCODE_ERROR`.

- [ ] **Step 35 of 60: Prove canonical crop and embedding continuity**

  Compare DeepStream output to approved ArcFace oracle for same-person/fifferent-person pairs,
  batch-1/batch-N, repeated runs, and all three GPUs. Store engine/model/preprocess hashes with
  evidence. Differences beyond tolerance block gallery writes because they would create a second
  embedding space.

### Task 8: Complete the persistent worker and Python scheduler

**Files:**
- Modify: `backend/pipeline/src/pipeline.cpp`
- Modify: `backend/pipeline/src/worker_main.cpp`
- Create: `backend/app/infrastructure/gpu/__init__.py`
- Create: `backend/app/infrastructure/gpu/contracts.py`
- Create: `backend/app/infrastructure/gpu/worker_client.py`
- Create: `backend/app/infrastructure/gpu/scheduler.py`
- Test: `backend/tests/contract/test_worker_protocol.py`
- Test: `backend/tests/integration/gpu/test_gpu_scheduler.py`

**Interfaces:**
- Consumes: complete native `ImageResult` from Tasks 3-7.
- Produces:
  `await GpuScheduler.process_image(request_id: str, encoded_jpeg: bytes) -> GpuImageResult`.

- [ ] **Step 36 of 60: Define strict Python DTO validation**

  Use frozen dataclasses/Pydantic models with exact lengths and ranges:

  ```python
  @dataclass(frozen=True)
  class BoundingBox:
      x: float
      y: float
      width: float
      height: float

  @dataclass(frozen=True)
  class GpuFaceResult:
      ordinal: int
      bounding_box: BoundingBox
      landmarks: Sequence[tuple[float, float]]    # validator requires exactly five
      detector_confidence: float
      embedding: Sequence[float]                  # validator requires 512 finite values
      aligned_jpeg: bytes                         # JPEG, bounded size

  @dataclass(frozen=True)
  class GpuImageResult:
      request_id: str
      gpu_id: int
      faces: Sequence[GpuFaceResult]
  ```

- [ ] **Step 37 of 60: Implement reconnect-safe Unix worker clients**

  Maintain one connection pool per socket, serialize writes per stream connection, enforce
  connect/request timeouts, validate matching `request_id`, cap response size, and map worker
  codes to sanitized infrastructure exceptions. Never retry a request after uncertain worker
  completion without the same request ID.

- [ ] **Step 38 of 60: Implement bounded least-loaded scheduling**

  Create one `asyncio.Semaphore(max_inflight_per_gpu)` per configured worker. Select the healthy
  worker with the lowest in-flight count and round-robin ties. If all queues are full, wait only
  `gpu_queue_timeout_seconds`, then return `GPU_BUSY`; never accumulate an unbounded Python list.

- [ ] **Step 39 of 60: Add readiness and failure semantics**

  Readiness requires all configured worker sockets to respond with protocol/runtime/model hashes
  matching settings. A single dead worker is removed from scheduling and reported degraded; all
  workers dead makes readiness fail. In-flight systemic failure returns `GPU_PIPELINE_ERROR`, not
  corrupt-image or no-face.

- [ ] **Step 40 of 60: Run three-GPU concurrency and teardown tests**

  Send mixed valid/no-face/corrupt batches concurrently, assert every request completes once,
  load distributes across GPU IDs `0,1,2`, result order is stable, backpressure is bounded, and
  worker restart does not duplicate a completed request. Stop all workers and verify exit `0`, no
  socket leaks/segfault, and GPU memory returns to measured baseline.

## Packet 4: Identity, Persistence, and Recognition

### Task 9: Refactor cross-store persistence for process-level workflows

**Files:**
- Modify: `backend/app/infrastructure/database/repositories/identity_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/sample_repository.py`
- Modify: `backend/app/infrastructure/database/repositories/result_repository.py`
- Modify: `backend/app/infrastructure/vector_store/qdrant_adapter.py`
- Modify: `backend/app/infrastructure/object_storage/minio_adapter.py`
- Modify: `backend/app/services/face_sample_persistence_service.py`
- Modify: `backend/app/services/storage_reconciliation_service.py`
- Test: `backend/tests/integration/services/test_face_sample_persistence.py`
- Test: `backend/tests/integration/services/test_storage_reconciliation.py`

**Interfaces:**
- Consumes: compact `GpuFaceResult` and an already-created process.
- Produces:
  `persist_sample(...) -> FaceSample`, `persist_samples(...) -> list[FaceSample]`, and
  `delete_sample(face_id, sample_id) -> FaceSample` without creating/completing processes.

- [ ] **Step 41 of 60: Write failing multi-face/process and deletion tests**

  Reproduce the current defect: `FaceSamplePersistenceService.persist()` creates an `enroll`
  process per sample, so two faces cannot share one recognition process. New tests create one
  process, persist two samples, complete once, retry both, and assert one process/two samples/two
  vectors/two objects. Add sample deletion tests asserting PG inactive, Qdrant absent/inactive,
  MinIO object removed, and historical result retained.

- [ ] **Step 42 of 60: Make repositories lifecycle-complete**

  Add exact methods:

  ```python
  FaceIdentityRepository.get_active_by_id(session, face_id)
  FaceIdentityRepository.update_known(session, face_id, name, metadata, expected_version)
  FaceIdentityRepository.soft_delete(session, face_id)  # sets is_active=False, deleted_at=now
  FaceSampleRepository.get_active_by_id(session, sample_id)
  FaceSampleRepository.list_by_face(session, face_id, active_only=True)
  FaceSampleRepository.set_inactive(session, sample_id)  # sets deleted_at=now
  RecognitionResultRepository.get_by_face(session, face_id)
  ```

  Updates must check active state and optimistic `version`; repositories still never commit.

- [ ] **Step 43 of 60: Add safe vector/storage micro-batch operations**

  Add typed `VectorUpsert` and implement `QdrantAdapter.upsert_many()` with one `wait=True`
  request plus `query_many()` using Qdrant's batch query API. Validate every vector/payload before
  issuing the request. MinIO has no transactional batch API: implement bounded concurrent
  `upload_aligned_samples()` and return per-sample success/failure without hiding partial writes.

  ```python
  @dataclass(frozen=True)
  class VectorUpsert:
      sample_id: str
      face_id: str
      vector: Sequence[float]
      embedding_model_version: str
      preprocess_version: str

  @dataclass(frozen=True)
  class SamplePersistenceInput:
      face_id: str
      sample_id: str
      aligned_jpeg: bytes
      embedding: Sequence[float]
      bounding_box: dict
      landmarks: dict
      detector_confidence: float
      identity_status: str
      name: str | None
      metadata: dict
  ```

- [ ] **Step 44 of 60: Refactor sample persistence ownership**

  Replace `persist()` with these exact public methods:

  - `persist_sample(*, process_id: str, sample: SamplePersistenceInput) -> FaceSample`
  - `persist_samples(*, process_id: str, samples: list[SamplePersistenceInput]) -> list[FaceSample]`
  - `delete_sample(*, process_id: str, face_id: str, sample_id: str) -> FaceSample`

  It may create/reuse identity/sample and emit events, but must not create, complete, or overwrite
  the caller's process record. Keep the explicit `pending -> blob_ready -> active` order and
  deterministic key. Make failure recording best-effort without swallowing the primary raised
  `ServiceError`.

- [ ] **Step 45 of 60: Implement idempotent sample/identity removal and reconciliation**

  Deactivate PG first, then Qdrant, then MinIO; retries treat already-absent external resources as
  success. If an external delete fails, retain inactive PG truth, emit a sanitized reconcile
  event, and let reconciliation retry cleanup. Identity deletion deactivates all samples in one
  PG transaction before external cleanup. Run all existing 37 Sprint 01 tests plus new lifecycle
  tests against real PostgreSQL, MinIO, and Qdrant.

### Task 10: Implement complete recognition workflow

**Files:**
- Create: `backend/app/services/recognition_service.py`
- Create: `backend/app/presentation/process_context.py`
- Create: `backend/app/presentation/schemas/recognition.py`
- Create: `backend/app/presentation/controllers/recognition_controller.py`
- Create: `backend/app/presentation/routers/face_router.py`
- Modify: `backend/app/services/exceptions.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/integration/services/test_recognition_service.py`
- Test: `backend/tests/integration/api/test_recognize.py`

**Interfaces:**
- Consumes: one JPEG, UUIDv7 process ID, `GpuScheduler`, repositories, Qdrant, persistence service.
- Produces: `RecognitionResponse(processId, faceCount, faces)` matching the approved API contract.

- [ ] **Step 46 of 60: Write requirement-level recognition tests first**

  Cover empty, oversized, PNG, corrupt JPEG, valid no-face, one unseen face, repeat anonymous,
  enrolled known, multi-face mixed known/anonymous, and GPU systemic failure. Assert process ID in
  success/error, no-face HTTP success, every face ID non-null, anonymous PII empty, original bbox,
  and immutable result snapshots.

- [ ] **Step 47 of 60: Create process context before validation**

  Generate UUIDv7 in middleware/dependency, store it at `request.state.process_id`, and add
  `X-Process-ID` to every producible response. Service errors must carry an HTTP status and stable
  code (`EMPTY_IMAGE`, `IMAGE_TOO_LARGE`, `UNSUPPORTED_MEDIA_TYPE`, `CORRUPT_IMAGE`, `GPU_BUSY`,
  `GPU_PIPELINE_ERROR`, `PERSISTENCE_ERROR`). Error JSON includes `processId`, `error`, `message`.

- [ ] **Step 48 of 60: Implement batch matching with PostgreSQL validation**

  Call one GPU request, then one Qdrant batch query for all embeddings with active/model/preprocess
  filters and top-k candidates. For each hit in descending score order, load sample and identity;
  accept only active matching versions. If score is below `recognition_threshold`, treat it as no
  match. Remove `anonymous_threshold` from behavior; `known` versus `anonymous` is the accepted
  identity's PostgreSQL lifecycle.

- [ ] **Step 49 of 60: Persist unmatched faces and immutable results atomically where possible**

  Create the process once as `recognize`. For each unmatched face preallocate UUIDv7 `face_id`,
  `sample_id`, and `result_id`, persist canonical sample, then create `RecognitionResult` with
  `new_anonymous` and `match_confidence=0.0`. Matched faces create results with current status/name/
  metadata snapshot and selected `sample_id`/score. Complete the process once with total face
  count. Any required new-anonymous persistence failure fails the request; auxiliary event failure
  does not rewrite a committed result.

- [ ] **Step 50 of 60: Expose and verify `POST /api/v1/faces/recognize`**

  Router accepts exactly one multipart `image`, performs boundary byte/content checks only, and
  delegates through controller to service. Run API tests with real dependencies and worker;
  repeat the same face across requests and restart to prove stable `faceId`. Verify multi-face
  result order follows detector ordinal and `confidence` is match score, not detector score.

## Packet 5: Enrollment, Management, and Traceability

### Task 11: Implement enrollment, sample, identity, and process APIs

**Files:**
- Create: `backend/app/services/enrollment_service.py`
- Create: `backend/app/services/identity_service.py`
- Create: `backend/app/presentation/schemas/enrollment.py`
- Create: `backend/app/presentation/schemas/identity.py`
- Create: `backend/app/presentation/schemas/process.py`
- Create: `backend/app/presentation/controllers/enrollment_controller.py`
- Create: `backend/app/presentation/controllers/identity_controller.py`
- Create: `backend/app/presentation/controllers/process_controller.py`
- Create: `backend/app/presentation/routers/process_router.py`
- Modify: `backend/app/presentation/routers/face_router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/api/test_enrollment.py`
- Test: `backend/tests/integration/api/test_identity_management.py`
- Test: `backend/tests/integration/api/test_history_process.py`

**Interfaces:**
- Consumes: exact-one-face GPU result and existing lifecycle services.
- Produces every face/process/sample endpoint in the approved design.

- [ ] **Step 51 of 60: Write the full endpoint acceptance matrix first**

  Tests must cover new known enrollment, anonymous promotion preserving `faceId`, promotion with
  optional new image, same known identity additional sample, zero-face rejection, multi-face
  rejection, mismatched target sample rejection, get/update/delete identity, list/delete sample,
  last-sample deletion, face history, process details, not-found, version conflict, and retry
  idempotency.

- [ ] **Step 52 of 60: Implement exact enrollment decision table**

  ```text
  image + no faceId -> detect exactly one; search gallery;
                       no match=create known; anonymous match=promote same faceId;
                       known same-name=add sample; known different-name=CONFLICT
  faceId + no image -> active anonymous only; promote same faceId
  faceId + image    -> exact one face; verify supplied identity match when it has active samples;
                       persist sample, then promote/update same faceId
  neither           -> INVALID_ENROLLMENT_REQUEST
  ```

  All successful modes store name/metadata only on known identity and preserve historical results.

- [ ] **Step 53 of 60: Implement sample and identity lifecycle operations**

  `POST /faces/{faceId}/samples` accepts one JPEG and requires exactly one face. If target has
  active samples, the best valid match must resolve to that `faceId` above threshold; otherwise
  return `SAMPLE_IDENTITY_MISMATCH`. GET lists technical sample metadata without exposing MinIO
  secrets. DELETE sample/identity is idempotent soft lifecycle with external cleanup and retained
  history. PATCH requires `expectedVersion` and at least name or metadata.

- [ ] **Step 54 of 60: Implement query/history/process projections**

  Return current identity state separately from immutable history. Face history selects recognition
  results by `face_id` and returns process ID/timestamp/status snapshot. Process detail returns
  process metadata, ordered per-face results, and sanitized events. Deleted identities remain
  retrievable only through history/process projections; normal GET returns inactive/not-found per
  approved schema.

- [ ] **Step 55 of 60: Wire all routes and run Phase 1 behavioral acceptance**

  Include routers under `/api/v1`; retain the existing health route. Verify exact endpoints:

  ```text
  POST /faces/recognize
  POST /faces/enroll
  POST|GET /faces/{faceId}/samples
  DELETE /faces/{faceId}/samples/{sampleId}
  GET|PATCH|DELETE /faces/{faceId}
  GET /faces/{faceId}/history
  GET /processes/{processId}
  ```

  Run all API tests against real PostgreSQL/MinIO/Qdrant/GPU workers and update
  `PHASE1_REQUIREMENT_TRACEABILITY.md` with exact source symbols and evidence commands.

## Packet 6: Deployment, Bulk Throughput, and Final Evidence

### Task 12: Package, benchmark, and close Phase 1

**Files:**
- Create: `docker/deepstream-worker.Dockerfile`
- Create: `docker-compose.yml`
- Create: `backend/app/internal/__init__.py`
- Create: `backend/app/internal/bulk_enroll.py`
- Modify: `backend/Dockerfile`
- Modify: `backend/pyproject.toml`
- Modify: `backend/.env.example`
- Modify: `Makefile`
- Modify: `docs/implementation/CURRENT_SPRINT.md`
- Modify: `docs/implementation/PHASE1_REQUIREMENT_TRACEABILITY.md`
- Create: `docs/implementation/PHASE1_GPU_EVIDENCE.md`
- Test: `backend/tests/integration/test_bulk_enroll.py`

**Interfaces:**
- Consumes: completed services and workers.
- Produces: one-command deployment, internal dataset seeder, reproducible benchmark, final Phase 1
  acceptance evidence.

- [ ] **Step 56 of 60: Build pinned API and worker images**

  Verify `nvcr.io/nvidia/deepstream:9.0-triton-multiarch` exists before using it; record its digest
  and pin production builds to that digest. Worker multi-stage build compiles native code/plugins,
  copies configs and prebuilt engines, and runs as non-root where NVIDIA device/socket permissions
  allow. API image contains no CUDA/PyDS runtime. Both images expose real readiness commands.

- [ ] **Step 57 of 60: Define one-command three-GPU Compose deployment**

  Compose starts PostgreSQL, MinIO, Qdrant, API, and `gpu-worker-0/1/2`. Pin each worker to one GPU,
  mount a shared `/run/mvision` socket volume and read-only model/config artifacts, persist all
  data volumes, add dependency health conditions, and configure restart policies/resource limits.
  Engine paths, thresholds, batch policy, timeouts, JPEG quality, ports, and storage settings come
  from environment variables; no machine-specific `/home/user` path enters production source.

- [ ] **Step 58 of 60: Implement the non-public labeled-directory bulk utility**

  CLI contract:

  ```bash
  python -m app.internal.bulk_enroll \
    --source-dir /datasets/lfw \
    --concurrency 192 \
    --report /reports/lfw-run.json
  ```

  Interpret `source/person_name/*.jpg`, create/reuse one known identity per label, submit bounded
  concurrent image requests through `GpuScheduler`, enforce exactly one face, persist through the
  same enrollment service, batch safe PG/Qdrant operations, and report accepted/rejected/retried
  counts without putting names in MinIO keys or Qdrant payloads. This is CLI-only, not an API route.

- [ ] **Step 59 of 60: Benchmark and tune without changing semantics**

  Sweep source slots, mux/PGIE/SGIE batches, TensorRT profiles, nvJPEG encode batch, API/bulk
  concurrency, Qdrant upsert batch, MinIO concurrency, and PG transaction micro-batch. Report
  separately: decode-to-embedding FPS, compute-plus-evidence FPS, and durable end-to-end samples/s;
  also p50/p95, GPU utilization/memory, queue depth, rejects, retries, and exact hashes. Select the
  highest sustainable settings with zero semantic mismatch, no OOM, and bounded queues; do not
  claim or tune tests toward 600 FPS.

- [ ] **Step 60 of 60: Run final Phase 1 acceptance and stop**

  Add Make targets and execute from a cleanly built deployment:

  ```bash
  make phase1-static
  make phase1-foundation
  make phase1-gpu-contract
  make phase1-api-acceptance
  make phase1-restart-acceptance
  make phase1-benchmark
  make phase1-acceptance
  git diff --check
  git status --short
  ```

  Final acceptance must include all prior 37 integration tests plus real GPU no/one/multi-face,
  lifecycle, sample management, history, partial failure, retry, restart, three-worker benchmark,
  repeated clean teardown, no segfault, and GPU memory baseline return. Update traceability with
  `PASS/PARTIAL/BLOCKED/NOT_TESTED`; stop before any video/live work.

---

## Test and Evidence Rules

- Every implementation step begins with a failing test or real reproducer.
- Native parity uses fixed fixtures and exact tolerance; tests never lower thresholds or alter
  preprocessing to pass.
- GPU tests that skip are reported `NOT_TESTED`, never PASS.
- Cross-store tests use real isolated PostgreSQL, MinIO, and Qdrant instances.
- Runtime evidence records commands, versions, model/engine hashes, input hashes, and raw summary.
- Do not stop/kill unrelated GPU processes. If memory headroom is insufficient, report a blocker.
- After each task, run targeted tests, packet integration tests, static checks, `git diff --check`,
  and inspect `git status --short`. Do not commit unless the user explicitly authorizes it.

## Requirement Coverage Review

| Requirement | Implementation tasks |
|---|---|
| Valid/invalid image and no-face | Tasks 3, 10 |
| Detect all faces and original bbox | Tasks 4, 5 |
| Persistent face ID and three statuses | Tasks 9, 10 |
| Unknown persistence and promotion | Tasks 9, 10, 11 |
| Enrollment, query, update, delete, multiple samples | Task 11 |
| Unique process ID and retrieval | Tasks 10, 11 |
| Persistent non-blocking logs | Tasks 9-11 |
| Face history/process detail | Task 11 |
| API-only consistent contracts/errors | Tasks 10, 11 |
| Required result fields | Tasks 10, 11 |
| Docker/env/persistence | Task 12 |
| Future video/live compatibility without implementation | Tasks 2-8 shared native contracts only |

## Plan Self-Review

- All twelve `ProjectRequirements.md` groups map to concrete tasks and acceptance tests.
- Video, tracker, RTSP, live stream, UI, and public bulk APIs are absent.
- Existing five-table schema is preserved; no migration is planned unless implementation proves a
  missing constraint that cannot be expressed with current columns.
- Existing `FaceSamplePersistenceService` process-ownership defect is explicitly corrected.
- Python, C++, config, and protocol names are consistent across producer/consumer tasks.
- Model decode math is exact to the inspected three-output YOLO artifact.
- ArcFace graph-owned preprocessing/L2 behavior is not duplicated.
- No CPU production fallback, per-request pipeline, PyDS data plane, or DeepStream patch remains.
- Every implementation action has an exact file, interface, command, or explicit hard stop.
