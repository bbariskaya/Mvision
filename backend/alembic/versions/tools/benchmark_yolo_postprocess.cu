#include "mvision/yolo_postprocess.hpp"

#include <cuda_runtime_api.h>

#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>

namespace {

void require_cuda(cudaError_t status) {
  if (status != cudaSuccess) {
    throw std::runtime_error(cudaGetErrorString(status));
  }
}

}  // namespace

int main(int argc, char **argv) {
  const int batch_size = argc == 2 ? std::atoi(argv[1]) : 256;
  if (batch_size <= 0 || batch_size > 256) {
    return 2;
  }

  float *heads[3]{};
  const int areas[3] = {80 * 80, 40 * 40, 20 * 20};
  for (int head = 0; head < 3; ++head) {
    const std::size_t bytes = static_cast<std::size_t>(batch_size) *
                              mvision::kYoloFaceChannels * areas[head] * sizeof(float);
    require_cuda(cudaMalloc(&heads[head], bytes));
    require_cuda(cudaMemset(heads[head], 0, bytes));
  }

  void *workspace = nullptr;
  const std::size_t workspace_bytes = mvision::yolo_face_workspace_size(batch_size);
  require_cuda(cudaMalloc(&workspace, workspace_bytes));
  int *counts = nullptr;
  float *boxes = nullptr;
  float *scores = nullptr;
  float *landmarks = nullptr;
  require_cuda(cudaMalloc(&counts, batch_size * sizeof(int)));
  require_cuda(cudaMalloc(&boxes, static_cast<std::size_t>(batch_size) *
                                      mvision::kYoloFaceMaxDetections * 4 * sizeof(float)));
  require_cuda(cudaMalloc(&scores, static_cast<std::size_t>(batch_size) *
                                       mvision::kYoloFaceMaxDetections * sizeof(float)));
  require_cuda(cudaMalloc(&landmarks, static_cast<std::size_t>(batch_size) *
                                          mvision::kYoloFaceMaxDetections * 10 * sizeof(float)));
  const mvision::YoloFaceOutput output{counts, boxes, scores, landmarks};

  cudaEvent_t started;
  cudaEvent_t finished;
  require_cuda(cudaEventCreate(&started));
  require_cuda(cudaEventCreate(&finished));
  for (int warmup = 0; warmup < 10; ++warmup) {
    require_cuda(mvision::launch_yolo_face_postprocess(
        heads[0], heads[1], heads[2], batch_size, 0.9F, 0.45F, workspace, workspace_bytes,
        output, nullptr));
  }
  require_cuda(cudaDeviceSynchronize());

  constexpr int kIterations = 100;
  require_cuda(cudaEventRecord(started));
  for (int iteration = 0; iteration < kIterations; ++iteration) {
    require_cuda(mvision::launch_yolo_face_postprocess(
        heads[0], heads[1], heads[2], batch_size, 0.9F, 0.45F, workspace, workspace_bytes,
        output, nullptr));
  }
  require_cuda(cudaEventRecord(finished));
  require_cuda(cudaEventSynchronize(finished));
  float elapsed_ms = 0.0F;
  require_cuda(cudaEventElapsedTime(&elapsed_ms, started, finished));

  const double latency_ms = elapsed_ms / kIterations;
  const double fps = batch_size * 1000.0 / latency_ms;
  std::cout << std::fixed << std::setprecision(2) << "batch=" << batch_size
            << " workspace_mib=" << workspace_bytes / 1024.0 / 1024.0
            << " latency_ms=" << latency_ms << " fps=" << fps << '\n';

  cudaEventDestroy(finished);
  cudaEventDestroy(started);
  cudaFree(landmarks);
  cudaFree(scores);
  cudaFree(boxes);
  cudaFree(counts);
  cudaFree(workspace);
  for (float *head : heads) {
    cudaFree(head);
  }
  return 0;
}
