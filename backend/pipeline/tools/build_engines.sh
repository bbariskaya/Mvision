#!/usr/bin/env bash
set -euo pipefail

models_dir="${1:-/workspace/backend/models}"
target="${2:-all}"
engine_dir="${models_dir}/engines"
mkdir -p "${engine_dir}"

common_args=(
  --fp16
  --builderOptimizationLevel=5
  --memPoolSize=workspace:8G
  --skipInference
)

if [[ "${target}" == "all" || "${target}" == "yolo" ]]; then
  prepared_yolo="${models_dir}/generated/yolov8n_face_tensorrt.onnx"
  plugin_library="/workspace/build/pipeline/libmvision_yolo_plugin.so"
  if [[ ! -f "${plugin_library}" ]]; then
    echo "missing GPU postprocess plugin: ${plugin_library}" >&2
    exit 1
  fi
  python3 /workspace/backend/scripts/prepare_yolo_model.py \
    "${models_dir}/yolov8n-face.onnx" \
    "${prepared_yolo}"
  trtexec \
    --onnx="${prepared_yolo}" \
    --saveEngine="${engine_dir}/yolov8n-face-gpu-post-sm75-trt10.14-fp16-b256.engine" \
    --dynamicPlugins="${plugin_library}" \
    --minShapes=images:1x3x640x640 \
    --optShapes=images:64x3x640x640 \
    --maxShapes=images:256x3x640x640 \
    "${common_args[@]}" \
    2>&1 | tee "${engine_dir}/yolov8n-face-gpu-post-sm75-trt10.14-fp16-b256.build.log"
fi

if [[ "${target}" == "all" || "${target}" == "arcface" ]]; then
  prepared_arcface="${models_dir}/generated/arcface_r50_tensorrt.onnx"
  python3 /workspace/backend/scripts/prepare_arcface_model.py \
    "${models_dir}/arcface_r50_dynamic.onnx" \
    "${prepared_arcface}"
  trtexec \
    --onnx="${prepared_arcface}" \
    --saveEngine="${engine_dir}/arcface-r50-sm75-trt10.14-fp16-b256.engine" \
    --minShapes=input.1:1x3x112x112 \
    --optShapes=input.1:64x3x112x112 \
    --maxShapes=input.1:256x3x112x112 \
    "${common_args[@]}" \
    2>&1 | tee "${engine_dir}/arcface-r50-sm75-trt10.14-fp16-b256.build.log"
fi
