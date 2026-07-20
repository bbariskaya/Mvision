#pragma once

#include <cuda_runtime_api.h>

#include <cstddef>

namespace mvision {

inline constexpr int kYoloFaceChannels = 80;
inline constexpr int kYoloFaceAnchorCount = 80 * 80 + 40 * 40 + 20 * 20;
inline constexpr int kYoloFacePreNmsTopK = 1024;
inline constexpr int kYoloFaceMaxDetections = 100;

struct FaceCandidate {
  float x1;
  float y1;
  float x2;
  float y2;
  float score;
  float landmarks_xy[10];
};

cudaError_t launch_yolo_face_decode(const float *head_stride8, const float *head_stride16,
                                    const float *head_stride32, int batch_size,
                                    float confidence_threshold, FaceCandidate *candidates,
                                    cudaStream_t stream);

struct YoloFaceOutput {
  int *num_detections;
  float *boxes;
  float *scores;
  float *landmarks_xy;
};

std::size_t yolo_face_workspace_size(int batch_size);
cudaError_t launch_yolo_face_postprocess(
    const float *head_stride8, const float *head_stride16, const float *head_stride32,
    int batch_size, float confidence_threshold, float iou_threshold, void *workspace,
    std::size_t workspace_bytes, const YoloFaceOutput &output, cudaStream_t stream);

}  // namespace mvision
