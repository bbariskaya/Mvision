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
- Used behavior: Inspected dynamic-batch ONNX (`yolov8n-face.onnx`) that includes multi-scale outputs; used for detector shape reference.
- Rejected behavior: Not copied as production source; no root LICENSE verified.

## DeepStream / pipeline references

### `marcoslucianops/DeepStream-Yolo-Face` (local clone: `tmp/DeepStream-Yolo-Face`)

- URL: https://github.com/marcoslucianops/DeepStream-Yolo-Face
- Observed commit: `b46e259 Updates + DeepStream 8.0 support`
- License: MIT (`tmp/DeepStream-Yolo-Face/LICENSE.md`) + NVIDIA copyright portions.
- Classification: `ORACLE_ONLY`.
- Used behavior: Custom parser attaching landmarks via `NvDsInferInstanceMaskInfo.mask`; `parse-bbox-func-name` + `custom-lib-path` config pattern.
- Rejected behavior: Parser performs host NMS and per-proposal allocation; not copied into production hot path. Sample batch=1 FP32 config is not dynamic-batch evidence.

### `zhouyuchong/face-recognition-deepstream` (local clone: `tmp/face-recognition-deepstream`)

- URL: https://github.com/zhouyuchong/face-recognition-deepstream
- Observed commit: `d18cc58 pass test`
- License: MIT (`tmp/face-recognition-deepstream/LICENSE`)
- Classification: `ORACLE_ONLY`.
- Used behavior: Probe extracting SGIE tensor output and L2 normalization/cosine matching pattern; pipeline orchestration lessons.
- Rejected behavior: Probe copies 512-D output into Python/NumPy; performs L2/cosine on CPU; hardcoded `0.3` threshold. Not production hot path.

### `zhouyuchong/gst-nvinfer-custom` (local clone: `tmp/gst-nvinfer-custom`)

- URL: https://github.com/zhouyuchong/gst-nvinfer-custom
- Observed commit: `4ca3fc7 fix: sometimes wrong landmarks will cause error`
- License: No root LICENSE file found in local clone.
- Classification: `FORBIDDEN`.
- Used behavior: None.
- Rejected behavior: `install.sh` replaces system DeepStream `.so`/headers; patches `nvinfer`; uses OpenCV CPU similarity transform. Not installed or copied.

## Recognition model references

### `deepinsight/insightface`

- URL: https://github.com/deepinsight/insightface
- License: Code MIT; pretrained ArcFace weights (Glint360k/WebFace) are non-commercial research by default.
- Classification: `ORACLE_ONLY` for canonical 112×112 five-point ArcFace template and alignment parity.
- Used behavior: ArcFace R50 dynamic-batch ONNX (`models/arcface_r50_dynamic.onnx`) selected for Phase 1; input normalization and L2 normalization embedded.
- Rejected behavior: Python/OpenCV reference path not used as production runtime; R100/Glint360 not selected — R50 WebFace is the active Phase 1 model.

## Official sources

### NVIDIA DeepStream 9

- Source: Installed DeepStream headers/source and official documentation.
- Classification: `ADOPT` for API/contract decisions.
- Used behavior: `nvdspreprocess` custom-library API is the preferred extension point for landmark-aware GPU alignment. Python bindings are deprecated; native C++/GStreamer components preferred.
- Rejected behavior: None.
