#include "mvision/yolo_postprocess.hpp"

#include <cuda_runtime_api.h>

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {

bool near(float actual, float expected, float tolerance = 0.05F) {
  return std::abs(actual - expected) <= tolerance;
}

}  // namespace

int main() {
  constexpr int kBatch = 1;
  constexpr int kHeight = 20;
  constexpr int kWidth = 20;
  constexpr int kArea = kHeight * kWidth;
  std::vector<float> host_head8(kBatch * mvision::kYoloFaceChannels * 80 * 80, 0.0F);
  std::vector<float> host_head16(kBatch * mvision::kYoloFaceChannels * 40 * 40, 0.0F);
  std::vector<float> host_head32(kBatch * mvision::kYoloFaceChannels * kArea, 0.0F);

  const int anchor = 0;
  for (int side = 0; side < 4; ++side) {
    host_head32[(side * 16 + 2) * kArea + anchor] = 100.0F;
  }
  host_head32[64 * kArea + anchor] = 10.0F;
  for (int landmark = 0; landmark < 5; ++landmark) {
    host_head32[(65 + landmark * 3) * kArea + anchor] = 0.25F;
    host_head32[(66 + landmark * 3) * kArea + anchor] = 0.50F;
  }

  float *device_head8 = nullptr;
  float *device_head16 = nullptr;
  float *device_head32 = nullptr;
  mvision::FaceCandidate *device_candidates = nullptr;
  cudaMalloc(&device_head8, host_head8.size() * sizeof(float));
  cudaMalloc(&device_head16, host_head16.size() * sizeof(float));
  cudaMalloc(&device_head32, host_head32.size() * sizeof(float));
  cudaMalloc(&device_candidates, mvision::kYoloFaceAnchorCount * sizeof(mvision::FaceCandidate));
  cudaMemcpy(device_head8, host_head8.data(), host_head8.size() * sizeof(float),
             cudaMemcpyHostToDevice);
  cudaMemcpy(device_head16, host_head16.data(), host_head16.size() * sizeof(float),
             cudaMemcpyHostToDevice);
  cudaMemcpy(device_head32, host_head32.data(), host_head32.size() * sizeof(float),
             cudaMemcpyHostToDevice);

  const cudaError_t launch_status = mvision::launch_yolo_face_decode(
      device_head8, device_head16, device_head32, kBatch, 0.9F, device_candidates, nullptr);
  if (launch_status != cudaSuccess || cudaDeviceSynchronize() != cudaSuccess) {
    return 1;
  }

  mvision::FaceCandidate candidate{};
  cudaMemcpy(&candidate, device_candidates + 8000, sizeof(candidate), cudaMemcpyDeviceToHost);

  if (!near(candidate.score, 0.99995F) || !near(candidate.x1, -48.0F) ||
      !near(candidate.y1, -48.0F) || !near(candidate.x2, 80.0F) ||
      !near(candidate.y2, 80.0F) || !near(candidate.landmarks_xy[0], 16.0F) ||
      !near(candidate.landmarks_xy[1], 32.0F)) {
    std::cerr << "unexpected decoded candidate: score=" << candidate.score
              << " box=" << candidate.x1 << ',' << candidate.y1 << ',' << candidate.x2 << ','
              << candidate.y2 << " landmark0=" << candidate.landmarks_xy[0] << ','
              << candidate.landmarks_xy[1] << '\n';
    return 1;
  }

  const int second_anchor = 1;
  for (int side = 0; side < 4; ++side) {
    host_head32[(side * 16 + 2) * kArea + second_anchor] = 100.0F;
  }
  host_head32[64 * kArea + second_anchor] = 9.0F;
  cudaMemcpy(device_head32, host_head32.data(), host_head32.size() * sizeof(float),
             cudaMemcpyHostToDevice);

  void *workspace = nullptr;
  const std::size_t workspace_bytes = mvision::yolo_face_workspace_size(kBatch);
  cudaMalloc(&workspace, workspace_bytes);
  int *device_count = nullptr;
  float *device_boxes = nullptr;
  float *device_scores = nullptr;
  float *device_landmarks = nullptr;
  cudaMalloc(&device_count, sizeof(int));
  cudaMalloc(&device_boxes, mvision::kYoloFaceMaxDetections * 4 * sizeof(float));
  cudaMalloc(&device_scores, mvision::kYoloFaceMaxDetections * sizeof(float));
  cudaMalloc(&device_landmarks, mvision::kYoloFaceMaxDetections * 10 * sizeof(float));
  const mvision::YoloFaceOutput output{
      device_count, device_boxes, device_scores, device_landmarks};

  const cudaError_t postprocess_status = mvision::launch_yolo_face_postprocess(
      device_head8, device_head16, device_head32, kBatch, 0.9F, 0.45F, workspace,
      workspace_bytes, output, nullptr);
  int detection_count = 0;
  float top_score = 0.0F;
  cudaMemcpy(&detection_count, device_count, sizeof(int), cudaMemcpyDeviceToHost);
  cudaMemcpy(&top_score, device_scores, sizeof(float), cudaMemcpyDeviceToHost);
  cudaFree(device_landmarks);
  cudaFree(device_scores);
  cudaFree(device_boxes);
  cudaFree(device_count);
  cudaFree(workspace);
  cudaFree(device_candidates);
  cudaFree(device_head32);
  cudaFree(device_head16);
  cudaFree(device_head8);

  if (postprocess_status != cudaSuccess || detection_count != 1 || !near(top_score, 0.99995F)) {
    std::cerr << "unexpected NMS result: status=" << cudaGetErrorString(postprocess_status)
              << " count=" << detection_count << " score=" << top_score << '\n';
    return 1;
  }
  return 0;
}
