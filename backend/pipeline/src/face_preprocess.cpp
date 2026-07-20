#include "mvision/face_align.hpp"

#include <string>
#include <unordered_map>
#include <vector>

#include <nvdspreprocess_interface.h>

#include <cuda_runtime_api.h>
#include <nvbufsurftransform.h>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>

struct CustomCtx {
  int gpu_id = 0;
  int max_batch = 0;
  cudaStream_t stream = nullptr;
  const std::uint8_t **host_inputs = nullptr;
  std::size_t *host_pitches = nullptr;
  float *host_landmarks = nullptr;
  const std::uint8_t **device_inputs = nullptr;
  std::size_t *device_pitches = nullptr;
  float *device_landmarks = nullptr;
  std::uint8_t *aligned_rgb = nullptr;
};

namespace {

void release_context(CustomCtx *ctx) {
  if (ctx == nullptr) {
    return;
  }
  if (ctx->gpu_id >= 0) {
    cudaSetDevice(ctx->gpu_id);
  }
  cudaFree(ctx->aligned_rgb);
  cudaFree(ctx->device_landmarks);
  cudaFree(ctx->device_pitches);
  cudaFree(ctx->device_inputs);
  cudaFreeHost(ctx->host_landmarks);
  cudaFreeHost(ctx->host_pitches);
  cudaFreeHost(ctx->host_inputs);
  if (ctx->stream != nullptr) {
    cudaStreamDestroy(ctx->stream);
  }
  delete ctx;
}

bool allocate_context(CustomCtx *ctx) {
  const std::size_t input_pointer_bytes = ctx->max_batch * sizeof(std::uint8_t *);
  const std::size_t pitch_bytes = ctx->max_batch * sizeof(std::size_t);
  const std::size_t landmark_bytes = ctx->max_batch * 10 * sizeof(float);
  const std::size_t rgb_bytes = static_cast<std::size_t>(ctx->max_batch) *
                                mvision::kAlignedFaceWidth * mvision::kAlignedFaceHeight *
                                mvision::kAlignedFaceChannels;
  return cudaStreamCreateWithFlags(&ctx->stream, cudaStreamNonBlocking) == cudaSuccess &&
         cudaHostAlloc(&ctx->host_inputs, input_pointer_bytes, cudaHostAllocPortable) ==
              cudaSuccess &&
         cudaHostAlloc(&ctx->host_pitches, pitch_bytes, cudaHostAllocPortable) == cudaSuccess &&
         cudaHostAlloc(&ctx->host_landmarks, landmark_bytes, cudaHostAllocPortable) == cudaSuccess &&
         cudaMalloc(&ctx->device_inputs, input_pointer_bytes) == cudaSuccess &&
         cudaMalloc(&ctx->device_pitches, pitch_bytes) == cudaSuccess &&
         cudaMalloc(&ctx->device_landmarks, landmark_bytes) == cudaSuccess &&
         cudaMalloc(&ctx->aligned_rgb, rgb_bytes) == cudaSuccess;
}

}  // namespace

extern "C" CustomCtx *initLib(CustomInitParams init_params) {
  if (init_params.tensor_params.network_input_shape.size() != 4 ||
      init_params.tensor_params.network_input_shape[1] != mvision::kAlignedFaceChannels ||
      init_params.tensor_params.network_input_shape[2] != mvision::kAlignedFaceHeight ||
      init_params.tensor_params.network_input_shape[3] != mvision::kAlignedFaceWidth) {
    return nullptr;
  }

  auto *ctx = new (std::nothrow) CustomCtx();
  if (ctx == nullptr) {
    return nullptr;
  }
  const auto gpu_config = init_params.user_configs.find("gpu-id");
  ctx->gpu_id = gpu_config == init_params.user_configs.end() ? 0 : std::stoi(gpu_config->second);
  ctx->max_batch = init_params.tensor_params.network_input_shape[0];
  if (ctx->max_batch <= 0 || cudaSetDevice(ctx->gpu_id) != cudaSuccess || !allocate_context(ctx)) {
    release_context(ctx);
    return nullptr;
  }
  return ctx;
}

extern "C" void deInitLib(CustomCtx *ctx) { release_context(ctx); }

extern "C" NvDsPreProcessStatus MvisionCustomTransformation(
    NvBufSurface *input, NvBufSurface *output, CustomTransformParams &params) {
  if (NvBufSurfTransformSetSessionParams(&params.transform_config_params) !=
      NvBufSurfTransformError_Success) {
    return NVDSPREPROCESS_CUSTOM_TRANSFORMATION_FAILED;
  }
  return NvBufSurfTransformAsync(input, output, &params.transform_params, &params.sync_obj) ==
                 NvBufSurfTransformError_Success
             ? NVDSPREPROCESS_SUCCESS
             : NVDSPREPROCESS_CUSTOM_TRANSFORMATION_FAILED;
}

extern "C" NvDsPreProcessStatus MvisionCustomTensorPreparation(
    CustomCtx *ctx, NvDsPreProcessBatch *batch, NvDsPreProcessCustomBuf *&buffer,
    CustomTensorParams &tensor_params, NvDsPreProcessAcquirer *acquirer) {
  if (ctx == nullptr || batch == nullptr || acquirer == nullptr || batch->units.empty()) {
    return NVDSPREPROCESS_INVALID_PARAMS;
  }
  const int face_count = static_cast<int>(batch->units.size());
  if (face_count > ctx->max_batch || cudaSetDevice(ctx->gpu_id) != cudaSuccess) {
    return NVDSPREPROCESS_INVALID_PARAMS;
  }

  for (int index = 0; index < face_count; ++index) {
    const auto &unit = batch->units[index];
    const auto *object = unit.roi_meta.object_meta;
    if (object == nullptr || object->mask_params.data == nullptr ||
        object->mask_params.size < 15 * sizeof(float) || unit.converted_frame_ptr == nullptr ||
        unit.roi_meta.converted_buffer == nullptr || object->rect_params.width <= 0.0F ||
        object->rect_params.height <= 0.0F) {
      return NVDSPREPROCESS_INVALID_PARAMS;
    }
    ctx->host_inputs[index] = static_cast<const std::uint8_t *>(unit.converted_frame_ptr);
    ctx->host_pitches[index] = unit.roi_meta.converted_buffer->pitch;
    for (int landmark = 0; landmark < 5; ++landmark) {
      ctx->host_landmarks[index * 10 + landmark * 2] =
          (object->mask_params.data[landmark * 3] - object->rect_params.left) *
          mvision::kAlignedFaceWidth / object->rect_params.width;
      ctx->host_landmarks[index * 10 + landmark * 2 + 1] =
          (object->mask_params.data[landmark * 3 + 1] - object->rect_params.top) *
          mvision::kAlignedFaceHeight / object->rect_params.height;
    }
  }

  buffer = acquirer->acquire();
  if (buffer == nullptr || buffer->memory_ptr == nullptr) {
    return NVDSPREPROCESS_RESOURCE_ERROR;
  }
  const std::size_t input_pointer_bytes = face_count * sizeof(std::uint8_t *);
  const std::size_t pitch_bytes = face_count * sizeof(std::size_t);
  const std::size_t landmark_bytes = face_count * 10 * sizeof(float);
  cudaError_t cuda_status = cudaMemcpyAsync(ctx->device_inputs, ctx->host_inputs,
                                            input_pointer_bytes, cudaMemcpyHostToDevice,
                                            ctx->stream);
  if (cuda_status == cudaSuccess) {
    cuda_status = cudaMemcpyAsync(ctx->device_pitches, ctx->host_pitches, pitch_bytes,
                                  cudaMemcpyHostToDevice, ctx->stream);
  }
  if (cuda_status == cudaSuccess) {
    cuda_status = cudaMemcpyAsync(ctx->device_landmarks, ctx->host_landmarks, landmark_bytes,
                                  cudaMemcpyHostToDevice, ctx->stream);
  }
  if (cuda_status == cudaSuccess) {
    cuda_status = mvision::launch_face_alignment(
        ctx->device_inputs, ctx->device_pitches, ctx->device_landmarks, face_count,
        ctx->aligned_rgb, static_cast<float *>(buffer->memory_ptr), ctx->stream);
  }
  if (cuda_status == cudaSuccess) {
    cuda_status = cudaStreamSynchronize(ctx->stream);
  }
  if (cuda_status != cudaSuccess) {
    acquirer->release(buffer);
    buffer = nullptr;
    return NVDSPREPROCESS_CUDA_ERROR;
  }
  tensor_params.params.network_input_shape[0] = face_count;
  return NVDSPREPROCESS_SUCCESS;
}
