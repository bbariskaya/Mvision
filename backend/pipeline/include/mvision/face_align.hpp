#pragma once

#include <cuda_runtime_api.h>

#include <cstddef>
#include <cstdint>

namespace mvision {

inline constexpr int kAlignedFaceWidth = 112;
inline constexpr int kAlignedFaceHeight = 112;
inline constexpr int kAlignedFaceChannels = 3;
inline constexpr float kArcFaceTemplate[10] = {
    38.2946F, 51.6963F, 73.5318F, 51.5014F, 56.0252F,
    71.7366F, 41.5493F, 92.3655F, 70.7299F, 92.2041F,
};

cudaError_t launch_face_alignment(const std::uint8_t *const *input_rgb,
                                  const std::size_t *input_pitch,
                                  const float *source_landmarks_xy, int batch_size,
                                  std::uint8_t *aligned_rgb, float *aligned_nchw,
                                  cudaStream_t stream);

}  // namespace mvision
