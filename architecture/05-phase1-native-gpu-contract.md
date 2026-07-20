# Phase 1 — Native GPU Contract (Sprint 02)

## Canonical Hot Path

```text
Encoded image
→ NVIDIA GPU decode
→ YOLOv8-Face candidate TensorRT
→ GPU bbox/confidence + 5 landmarks + GPU NMS
→ CUDA/NPP five-point alignment
→ ArcFace R50 TensorRT
→ GPU L2 normalize
→ Compact output boundary
```

## CPU Boundary
Only compact metadata crosses the GPU/CPU boundary:

- Bounding box, 5 landmarks, detector score, quality/rejection reason.
- GPU-L2-normalized 512-D embedding.
- GPU-encoded aligned face bytes for storage.

Nothing else leaves the GPU: no full decoded image, no full RGB/BGR, no detector tensors, no alignment input/output tensors, no unnormalized embeddings.

## Detector Candidate: YOLOv8-Face
`derronqi/yolov8-face` is the preferred candidate. Before locking:

- Verify weight/model license and provenance.
- Record artifact SHA-256.
- Inspect exact ONNX output (bbox, confidence, 5-landmark ordering).
- Build dynamic batch TensorRT profile.
- Design GPU postprocess/NMS.
- Validate batch-1 vs batch-N parity.

License warning: repository contains GPL-3.0 / AGPL-3.0 headers. Do not copy source without explicit license review.

## Recognizer: ArcFace R50
- Input: 112×112 aligned face.
- Pixel normalization and channel order from the exact exported model.
- Output: 512-D embedding.
- Canonical five-point landmark template.
- L2 normalization on GPU.

`model_version`/`preprocess_version` stored in `face_sample` and Qdrant payload for strict version matching.

## Prohibited Fallbacks
- PIL/Pillow/OpenCV decode, resize, crop, alignment.
- `cv2.VideoCapture`.
- FFmpeg CLI / PyAV CPU decode.
- NumPy detector decode, NMS, alignment, L2 normalization.
- `CPUExecutionProvider` fallback.
- DeepFace / InsightFace `FaceAnalysis` runtime.
- GPU error → silent CPU rerun.
- CUDA/TensorRT error reported as corrupt image.
