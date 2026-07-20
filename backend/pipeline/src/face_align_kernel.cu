#include "mvision/face_align.hpp"

#include <cuda_runtime.h>

#include <cstddef>
#include <cstdint>

namespace mvision {
namespace {

__device__ __constant__ float kTemplateDevice[10] = {
    38.2946F, 51.6963F, 73.5318F, 51.5014F, 56.0252F,
    71.7366F, 41.5493F, 92.3655F, 70.7299F, 92.2041F,
};

__device__ float sample_channel(const std::uint8_t *image, std::size_t pitch, float x, float y,
                                int channel) {
  if (x < 0.0F || y < 0.0F || x > kAlignedFaceWidth - 1.0F ||
      y > kAlignedFaceHeight - 1.0F) {
    return 0.0F;
  }
  const int x0 = static_cast<int>(floorf(x));
  const int y0 = static_cast<int>(floorf(y));
  const int x1 = min(x0 + 1, kAlignedFaceWidth - 1);
  const int y1 = min(y0 + 1, kAlignedFaceHeight - 1);
  const float dx = x - x0;
  const float dy = y - y0;
  const float top = image[y0 * pitch + x0 * 3 + channel] * (1.0F - dx) +
                    image[y0 * pitch + x1 * 3 + channel] * dx;
  const float bottom = image[y1 * pitch + x0 * 3 + channel] * (1.0F - dx) +
                       image[y1 * pitch + x1 * 3 + channel] * dx;
  return top * (1.0F - dy) + bottom * dy;
}

__global__ void align_kernel(const std::uint8_t *const *input_rgb,
                             const std::size_t *input_pitch, const float *source_landmarks_xy,
                             int batch_size, std::uint8_t *aligned_rgb, float *aligned_nchw) {
  const int face = blockIdx.x;
  if (face >= batch_size) {
    return;
  }

  __shared__ float transform_a;
  __shared__ float transform_b;
  __shared__ float translate_x;
  __shared__ float translate_y;
  __shared__ int valid;
  if (threadIdx.x == 0) {
    const float *source = source_landmarks_xy + face * 10;
    float source_mean_x = 0.0F;
    float source_mean_y = 0.0F;
    float target_mean_x = 0.0F;
    float target_mean_y = 0.0F;
    for (int point = 0; point < 5; ++point) {
      source_mean_x += source[point * 2];
      source_mean_y += source[point * 2 + 1];
      target_mean_x += kTemplateDevice[point * 2];
      target_mean_y += kTemplateDevice[point * 2 + 1];
    }
    source_mean_x *= 0.2F;
    source_mean_y *= 0.2F;
    target_mean_x *= 0.2F;
    target_mean_y *= 0.2F;

    float dot = 0.0F;
    float cross = 0.0F;
    float denominator = 0.0F;
    for (int point = 0; point < 5; ++point) {
      const float source_x = source[point * 2] - source_mean_x;
      const float source_y = source[point * 2 + 1] - source_mean_y;
      const float target_x = kTemplateDevice[point * 2] - target_mean_x;
      const float target_y = kTemplateDevice[point * 2 + 1] - target_mean_y;
      dot += source_x * target_x + source_y * target_y;
      cross += source_x * target_y - source_y * target_x;
      denominator += source_x * source_x + source_y * source_y;
    }
    valid = isfinite(denominator) && denominator > 1.0e-6F;
    if (valid != 0) {
      transform_a = dot / denominator;
      transform_b = cross / denominator;
      translate_x = target_mean_x - transform_a * source_mean_x + transform_b * source_mean_y;
      translate_y = target_mean_y - transform_b * source_mean_x - transform_a * source_mean_y;
      const float determinant =
          transform_a * transform_a + transform_b * transform_b;
      valid = isfinite(transform_a) && isfinite(transform_b) && determinant > 1.0e-8F;
    }
  }
  __syncthreads();

  constexpr int kPixels = kAlignedFaceWidth * kAlignedFaceHeight;
  for (int pixel = threadIdx.x; pixel < kPixels; pixel += blockDim.x) {
    float red = 0.0F;
    float green = 0.0F;
    float blue = 0.0F;
    if (valid != 0) {
      const float output_x = static_cast<float>(pixel % kAlignedFaceWidth);
      const float output_y = static_cast<float>(pixel / kAlignedFaceWidth);
      const float translated_x = output_x - translate_x;
      const float translated_y = output_y - translate_y;
      const float determinant = transform_a * transform_a + transform_b * transform_b;
      const float source_x =
          (transform_a * translated_x + transform_b * translated_y) / determinant;
      const float source_y =
          (-transform_b * translated_x + transform_a * translated_y) / determinant;
      red = sample_channel(input_rgb[face], input_pitch[face], source_x, source_y, 0);
      green = sample_channel(input_rgb[face], input_pitch[face], source_x, source_y, 1);
      blue = sample_channel(input_rgb[face], input_pitch[face], source_x, source_y, 2);
    }

    const int rgb_offset = face * kPixels * 3 + pixel * 3;
    aligned_rgb[rgb_offset] = static_cast<std::uint8_t>(__float2uint_rn(red));
    aligned_rgb[rgb_offset + 1] = static_cast<std::uint8_t>(__float2uint_rn(green));
    aligned_rgb[rgb_offset + 2] = static_cast<std::uint8_t>(__float2uint_rn(blue));
    const int tensor_offset = face * kPixels * 3;
    aligned_nchw[tensor_offset + pixel] = red;
    aligned_nchw[tensor_offset + kPixels + pixel] = green;
    aligned_nchw[tensor_offset + kPixels * 2 + pixel] = blue;
  }
}

}  // namespace

cudaError_t launch_face_alignment(const std::uint8_t *const *input_rgb,
                                  const std::size_t *input_pitch,
                                  const float *source_landmarks_xy, int batch_size,
                                  std::uint8_t *aligned_rgb, float *aligned_nchw,
                                  cudaStream_t stream) {
  if (input_rgb == nullptr || input_pitch == nullptr || source_landmarks_xy == nullptr ||
      aligned_rgb == nullptr || aligned_nchw == nullptr || batch_size <= 0) {
    return cudaErrorInvalidValue;
  }
  align_kernel<<<batch_size, 256, 0, stream>>>(input_rgb, input_pitch, source_landmarks_xy,
                                               batch_size, aligned_rgb, aligned_nchw);
  return cudaPeekAtLastError();
}

}  // namespace mvision
