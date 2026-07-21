#include "mvision/face_align.hpp"

#include <cuda_runtime_api.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

int main() {
  constexpr int kPixels = mvision::kAlignedFaceWidth * mvision::kAlignedFaceHeight;
  std::vector<std::uint8_t> input(kPixels * 4);
  for (int y = 0; y < mvision::kAlignedFaceHeight; ++y) {
    for (int x = 0; x < mvision::kAlignedFaceWidth; ++x) {
      const int pixel = y * mvision::kAlignedFaceWidth + x;
      input[pixel * 4] = static_cast<std::uint8_t>(x);
      input[pixel * 4 + 1] = static_cast<std::uint8_t>(y);
      input[pixel * 4 + 2] = 77;
      input[pixel * 4 + 3] = 255;
    }
  }

  std::uint8_t *device_input = nullptr;
  const std::uint8_t **device_input_array = nullptr;
  std::size_t *device_pitch = nullptr;
  float *device_landmarks = nullptr;
  std::uint8_t *device_rgb = nullptr;
  float *device_tensor = nullptr;
  cudaMalloc(&device_input, input.size());
  cudaMalloc(&device_input_array, sizeof(device_input));
  cudaMalloc(&device_pitch, sizeof(std::size_t));
  cudaMalloc(&device_landmarks, sizeof(mvision::kArcFaceTemplate));
  cudaMalloc(&device_rgb, input.size());
  cudaMalloc(&device_tensor, kPixels * 3 * sizeof(float));
  const std::size_t pitch = mvision::kAlignedFaceWidth * 4;
  cudaMemcpy(device_input, input.data(), input.size(), cudaMemcpyHostToDevice);
  cudaMemcpy(device_input_array, &device_input, sizeof(device_input), cudaMemcpyHostToDevice);
  cudaMemcpy(device_pitch, &pitch, sizeof(pitch), cudaMemcpyHostToDevice);
  cudaMemcpy(device_landmarks, mvision::kArcFaceTemplate, sizeof(mvision::kArcFaceTemplate),
             cudaMemcpyHostToDevice);

  const cudaError_t status = mvision::launch_face_alignment(
      device_input_array, device_pitch, device_landmarks, 1, device_rgb, device_tensor, nullptr);
  if (status != cudaSuccess || cudaDeviceSynchronize() != cudaSuccess) {
    return 1;
  }

  std::vector<std::uint8_t> output(input.size());
  std::vector<float> tensor(kPixels * 3);
  cudaMemcpy(output.data(), device_rgb, output.size(), cudaMemcpyDeviceToHost);
  cudaMemcpy(tensor.data(), device_tensor, tensor.size() * sizeof(float), cudaMemcpyDeviceToHost);
  cudaFree(device_tensor);
  cudaFree(device_rgb);
  cudaFree(device_landmarks);
  cudaFree(device_pitch);
  cudaFree(device_input_array);
  cudaFree(device_input);

  const int sample = 50 * mvision::kAlignedFaceWidth + 40;
  return output[sample * 3] == 40 && output[sample * 3 + 1] == 50 &&
                 output[sample * 3 + 2] == 77 && std::abs(tensor[sample] - 40.0F) < 0.01F &&
                 std::abs(tensor[kPixels + sample] - 50.0F) < 0.01F &&
                 std::abs(tensor[kPixels * 2 + sample] - 77.0F) < 0.01F
             ? 0
             : 1;
}
