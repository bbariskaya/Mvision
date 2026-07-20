# Reference Decision Log

Log of upstream repositories inspected and how they apply to Phase 1.

## Detector candidates

### `derronqi/yolov8-face` (preferred upstream candidate)

- URL: https://github.com/derronqi/yolov8-face
- License: GPL-3.0 (repository) with some source headers mentioning AGPL-3.0.
- Classification: `ORACLE_ONLY` until artifact/license/provenance gates pass.
- Used behavior: YOLOv8-Face with five-point landmark output layout; `--dynamic` ONNX export concept.
- Rejected behavior: Source not copied into production without explicit license review. Pretrained weight license is a separate release gate.
- Local clone: Not present in `tmp/`.

### `lindevs/yolov8-face` (local clone: `tmp/yolov8-face`)

- URL: https://github.com/lindevs/yolov8-face
- Observed commit: `c6a3dee update readme`
- License: MIT (`tmp/yolov8-face/LICENSE`)
- Classification: `ORACLE_ONLY` for ONNX export shape inspection.
- Used behavior: Confirmed YOLOv8-Face can be exported to ONNX; static batch 1×3×640×640 sample inspected.
- Rejected behavior: Local pre-exported `yolov8n-face-lindevs.onnx` lacks dynamic batch and five-landmark evidence needed for the hot path; not used as production detector.

### `yakhyo/yolov8-face-onnx-inference` (local clone: `tmp/yolov8-face-onnx`)

- URL: https://github.com/yakhyo/yolov8-face-onnx-inference
- Observed commit: `33f893f chore: Get the input shape from onnx model`
- License: No root LICENSE file found in local clone.
- Classification: `ORACLE_ONLY` for ONNX inference shape and output structure.
- Used behavior: `models/yolov8.py::postprocess` is an oracle for the active three-head layout:
  channels `64 DFL + 1 class + 15 keypoints`, strides `8/16/32`, half-offset bbox grid,
  integer keypoint grid, class sigmoid, and NMS. Production reimplementation remains CUDA-only.
- Rejected behavior: Not copied as production source; no root LICENSE verified.

## DeepStream / pipeline references

### `marcoslucianops/DeepStream-Yolo-Face` (local clone: `tmp/DeepStream-Yolo-Face`)

- URL: https://github.com/marcoslucianops/DeepStream-Yolo-Face
- Observed commit: `b46e259 Updates + DeepStream 8.0 support`
- License: MIT (`tmp/DeepStream-Yolo-Face/LICENSE.md`) + NVIDIA copyright portions.
- Classification: `ADAPT` for standard DeepStream metadata/config patterns.
- Used behavior: Custom parser attaching landmarks via `NvDsInferInstanceMaskInfo.mask`;
  `network-type=3`, `parse-bbox-instance-mask-func-name`, `output-instance-mask=1`, and
  `custom-lib-path` config pattern; CUDA-device `nvstreammux`; explicit `PLAYING -> NULL` teardown.
- Rejected behavior: Parser performs host NMS and per-proposal allocation; not copied into production hot path. Sample batch=1 FP32 config is not dynamic-batch evidence.

### `zhouyuchong/face-recognition-deepstream` (local clone: `tmp/face-recognition-deepstream`)

- URL: https://github.com/zhouyuchong/face-recognition-deepstream
- Observed commit: `d18cc58 pass test`
- License: MIT (`tmp/face-recognition-deepstream/LICENSE`)
- Classification: `ORACLE_ONLY`.
- Used behavior: Pipeline stage ordering and SGIE tensor association oracle.
- Rejected behavior: Patched-only `enable-output-landmark`, `network-type=100`, and
  `alignment-type=1`; probe copies 512-D output into Python/NumPy, performs L2/cosine on CPU,
  and hardcodes threshold `0.3`.

### `zhouyuchong/gst-nvinfer-custom` (local clone: `tmp/gst-nvinfer-custom`)

- URL: https://github.com/zhouyuchong/gst-nvinfer-custom
- Observed commit: `4ca3fc7 fix: sometimes wrong landmarks will cause error`
- License: No root LICENSE file found in local clone.
- Classification: `ORACLE_ONLY`; production dependency remains forbidden.
- Used behavior: ArcFace five-point template, transform direction, and NPP warp parity only.
- Rejected behavior: `install.sh` replaces system DeepStream `.so`/headers; patches `nvinfer`;
  computes Umeyama/SVD on CPU with OpenCV; allocates CUDA buffers in the processing loop; optional
  host debug copies. Not installed or copied.

## Recognition model references

### `deepinsight/insightface`

- URL: https://github.com/deepinsight/insightface
- License: Code MIT; pretrained ArcFace weights (Glint360k/WebFace) are non-commercial research by default.
- Classification: `ORACLE_ONLY` for canonical 112×112 five-point ArcFace template and alignment parity.
- Used behavior: ArcFace R50 dynamic-batch ONNX
  (`backend/models/arcface_r50_dynamic.onnx`) selected for Phase 1. Artifact inspection proves
  graph-owned `(input - 127.5) / 128` preprocessing and output `LpNormalization`.
- Rejected behavior: Python/OpenCV reference path not used as production runtime; R100/Glint360 not selected — R50 WebFace is the active Phase 1 model.

## Official sources

### NVIDIA DeepStream 9

- Source: Installed DeepStream headers/source and official documentation.
- Classification: `ADOPT` for API/contract decisions.
- Used behavior: `nvdspreprocess` custom-library API is the preferred extension point for landmark-aware GPU alignment. Python bindings are deprecated; native C++/GStreamer components preferred.
- Rejected behavior: None.

## Active model release gate

- User decision: YOLOv8-Face + ArcFace R50 are approved for current internal implementation and
  runtime validation. RetinaFace/GlintR100 decisions in `ProjectGoalandContext.md` are stale.
- YOLO artifact metadata declares AGPL-3.0. Upstream source is used as an oracle; no GPL/AGPL
  source is copied into proprietary production code.
- ArcFace code is MIT, but pretrained-weight/training-data terms require legal approval before an
  external/commercial release.
- Classification: `IMPLEMENTATION_ALLOWED_RELEASE_BLOCKED_LEGAL_REVIEW`.
