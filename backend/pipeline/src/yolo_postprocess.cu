#include "mvision/yolo_postprocess.hpp"

#include <cub/device/device_segmented_radix_sort.cuh>
#include <cuda_runtime.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>

namespace mvision {
namespace {

__device__ float tensor_value(const float *head, int batch, int channel, int anchor, int area) {
  return head[(batch * kYoloFaceChannels + channel) * area + anchor];
}

__device__ float dfl_distance(const float *head, int batch, int side, int anchor, int area) {
  const int first_channel = side * 16;
  float maximum = tensor_value(head, batch, first_channel, anchor, area);
  for (int bin = 1; bin < 16; ++bin) {
    maximum = fmaxf(maximum, tensor_value(head, batch, first_channel + bin, anchor, area));
  }

  float denominator = 0.0F;
  float weighted_sum = 0.0F;
  for (int bin = 0; bin < 16; ++bin) {
    const float probability =
        expf(tensor_value(head, batch, first_channel + bin, anchor, area) - maximum);
    denominator += probability;
    weighted_sum += probability * static_cast<float>(bin);
  }
  return weighted_sum / denominator;
}

__global__ void decode_kernel(const float *head_stride8, const float *head_stride16,
                              const float *head_stride32, int batch_size,
                              float confidence_threshold, FaceCandidate *candidates,
                              float *scores, int *indices) {
  const int linear_index = blockIdx.x * blockDim.x + threadIdx.x;
  const int total = batch_size * kYoloFaceAnchorCount;
  if (linear_index >= total) {
    return;
  }

  const int batch = linear_index / kYoloFaceAnchorCount;
  const int global_anchor = linear_index % kYoloFaceAnchorCount;
  const float *head = nullptr;
  int stride = 0;
  int width = 0;
  int area = 0;
  int anchor = 0;
  if (global_anchor < 6400) {
    head = head_stride8;
    stride = 8;
    width = 80;
    area = 6400;
    anchor = global_anchor;
  } else if (global_anchor < 8000) {
    head = head_stride16;
    stride = 16;
    width = 40;
    area = 1600;
    anchor = global_anchor - 6400;
  } else {
    head = head_stride32;
    stride = 32;
    width = 20;
    area = 400;
    anchor = global_anchor - 8000;
  }

  FaceCandidate &candidate = candidates[linear_index];
  const float class_logit = tensor_value(head, batch, 64, anchor, area);
  candidate.score = 1.0F / (1.0F + expf(-class_logit));
  if (candidate.score < confidence_threshold) {
    candidate.score = -INFINITY;
    if (scores != nullptr) {
      scores[linear_index] = candidate.score;
      indices[linear_index] = global_anchor;
    }
    return;
  }

  const int grid_x = anchor % width;
  const int grid_y = anchor / width;
  const float center_x = static_cast<float>(grid_x) + 0.5F;
  const float center_y = static_cast<float>(grid_y) + 0.5F;
  candidate.x1 = (center_x - dfl_distance(head, batch, 0, anchor, area)) * stride;
  candidate.y1 = (center_y - dfl_distance(head, batch, 1, anchor, area)) * stride;
  candidate.x2 = (center_x + dfl_distance(head, batch, 2, anchor, area)) * stride;
  candidate.y2 = (center_y + dfl_distance(head, batch, 3, anchor, area)) * stride;

  for (int landmark = 0; landmark < 5; ++landmark) {
    const float raw_x = tensor_value(head, batch, 65 + landmark * 3, anchor, area);
    const float raw_y = tensor_value(head, batch, 66 + landmark * 3, anchor, area);
    candidate.landmarks_xy[landmark * 2] =
        (raw_x * 2.0F + static_cast<float>(grid_x)) * stride;
    candidate.landmarks_xy[landmark * 2 + 1] =
        (raw_y * 2.0F + static_cast<float>(grid_y)) * stride;
  }
  if (scores != nullptr) {
    scores[linear_index] = candidate.score;
    indices[linear_index] = global_anchor;
  }
}

__global__ void initialize_segments_kernel(int batch_size, int *begin_offsets, int *end_offsets) {
  const int batch = blockIdx.x * blockDim.x + threadIdx.x;
  if (batch < batch_size) {
    begin_offsets[batch] = batch * kYoloFaceAnchorCount;
    end_offsets[batch] = (batch + 1) * kYoloFaceAnchorCount;
  }
}

__device__ float intersection_over_union(const FaceCandidate &left,
                                         const FaceCandidate &right) {
  const float intersection_width = fmaxf(0.0F, fminf(left.x2, right.x2) - fmaxf(left.x1, right.x1));
  const float intersection_height =
      fmaxf(0.0F, fminf(left.y2, right.y2) - fmaxf(left.y1, right.y1));
  const float intersection = intersection_width * intersection_height;
  const float left_area = fmaxf(0.0F, left.x2 - left.x1) * fmaxf(0.0F, left.y2 - left.y1);
  const float right_area =
      fmaxf(0.0F, right.x2 - right.x1) * fmaxf(0.0F, right.y2 - right.y1);
  const float union_area = left_area + right_area - intersection;
  return union_area > 0.0F ? intersection / union_area : 0.0F;
}

__global__ void nms_mask_kernel(const FaceCandidate *candidates, const float *sorted_scores,
                                const int *sorted_indices, int batch_size, float iou_threshold,
                                std::uint64_t *masks) {
  constexpr int kTile = 64;
  constexpr int kMaskWords = kYoloFacePreNmsTopK / kTile;
  const int column_block = blockIdx.x;
  const int row_block = blockIdx.y;
  const int batch = blockIdx.z;
  if (batch >= batch_size || column_block < row_block) {
    return;
  }

  __shared__ FaceCandidate column_candidates[kTile];
  const int column = column_block * kTile + threadIdx.x;
  if (column < kYoloFacePreNmsTopK) {
    const int sorted_offset = batch * kYoloFaceAnchorCount + column;
    const int candidate_index = sorted_indices[sorted_offset];
    column_candidates[threadIdx.x] =
        candidates[batch * kYoloFaceAnchorCount + candidate_index];
  }
  __syncthreads();

  const int row = row_block * kTile + threadIdx.x;
  if (row >= kYoloFacePreNmsTopK) {
    return;
  }
  const int row_sorted_offset = batch * kYoloFaceAnchorCount + row;
  std::uint64_t mask = 0;
  if (sorted_scores[row_sorted_offset] > -INFINITY) {
    const FaceCandidate row_candidate =
        candidates[batch * kYoloFaceAnchorCount + sorted_indices[row_sorted_offset]];
    const int first_column = column_block == row_block ? threadIdx.x + 1 : 0;
    for (int item = first_column; item < kTile; ++item) {
      const int absolute_column = column_block * kTile + item;
      if (absolute_column < kYoloFacePreNmsTopK &&
          intersection_over_union(row_candidate, column_candidates[item]) > iou_threshold) {
        mask |= std::uint64_t{1} << item;
      }
    }
  }
  masks[(batch * kYoloFacePreNmsTopK + row) * kMaskWords + column_block] = mask;
}

__global__ void select_detections_kernel(const FaceCandidate *candidates,
                                         const float *sorted_scores, const int *sorted_indices,
                                         float confidence_threshold, const std::uint64_t *masks,
                                         YoloFaceOutput output) {
  constexpr int kMaskWords = kYoloFacePreNmsTopK / 64;
  const int batch = blockIdx.x;
  if (threadIdx.x != 0) {
    return;
  }

  std::uint64_t suppressed[kMaskWords]{};
  int count = 0;
  for (int row = 0; row < kYoloFacePreNmsTopK && count < kYoloFaceMaxDetections; ++row) {
    const int sorted_offset = batch * kYoloFaceAnchorCount + row;
    if (sorted_scores[sorted_offset] < confidence_threshold) {
      break;
    }
    if ((suppressed[row / 64] & (std::uint64_t{1} << (row % 64))) != 0) {
      continue;
    }

    const FaceCandidate candidate =
        candidates[batch * kYoloFaceAnchorCount + sorted_indices[sorted_offset]];
    const int output_index = batch * kYoloFaceMaxDetections + count;
    output.scores[output_index] = candidate.score;
    output.boxes[output_index * 4] = candidate.x1;
    output.boxes[output_index * 4 + 1] = candidate.y1;
    output.boxes[output_index * 4 + 2] = candidate.x2;
    output.boxes[output_index * 4 + 3] = candidate.y2;
    for (int coordinate = 0; coordinate < 10; ++coordinate) {
      output.landmarks_xy[output_index * 10 + coordinate] = candidate.landmarks_xy[coordinate];
    }
    ++count;

    const std::uint64_t *row_masks =
        masks + (batch * kYoloFacePreNmsTopK + row) * kMaskWords;
    for (int word = row / 64; word < kMaskWords; ++word) {
      suppressed[word] |= row_masks[word];
    }
  }
  output.num_detections[batch] = count;
}

std::size_t align_up(std::size_t value, std::size_t alignment = 256) {
  return (value + alignment - 1) / alignment * alignment;
}

std::size_t sort_temporary_bytes(int batch_size) {
  std::size_t bytes = 0;
  cub::DeviceSegmentedRadixSort::SortPairsDescending(
      nullptr, bytes, static_cast<const float *>(nullptr), static_cast<float *>(nullptr),
      static_cast<const int *>(nullptr), static_cast<int *>(nullptr),
      batch_size * kYoloFaceAnchorCount, batch_size, static_cast<const int *>(nullptr),
      static_cast<const int *>(nullptr));
  return bytes;
}

struct WorkspaceView {
  FaceCandidate *candidates;
  float *scores_in;
  float *scores_out;
  int *indices_in;
  int *indices_out;
  int *begin_offsets;
  int *end_offsets;
  std::uint64_t *masks;
  void *sort_temporary;
  std::size_t sort_temporary_size;
};

WorkspaceView partition_workspace(void *workspace, int batch_size) {
  auto *cursor = static_cast<std::byte *>(workspace);
  auto take = [&cursor](std::size_t bytes) {
    std::byte *result = cursor;
    cursor += align_up(bytes);
    return result;
  };
  const std::size_t item_count = static_cast<std::size_t>(batch_size) * kYoloFaceAnchorCount;
  WorkspaceView view{};
  view.candidates = reinterpret_cast<FaceCandidate *>(take(item_count * sizeof(FaceCandidate)));
  view.scores_in = reinterpret_cast<float *>(take(item_count * sizeof(float)));
  view.scores_out = reinterpret_cast<float *>(take(item_count * sizeof(float)));
  view.indices_in = reinterpret_cast<int *>(take(item_count * sizeof(int)));
  view.indices_out = reinterpret_cast<int *>(take(item_count * sizeof(int)));
  view.begin_offsets = reinterpret_cast<int *>(take(batch_size * sizeof(int)));
  view.end_offsets = reinterpret_cast<int *>(take(batch_size * sizeof(int)));
  view.masks = reinterpret_cast<std::uint64_t *>(take(
      static_cast<std::size_t>(batch_size) * kYoloFacePreNmsTopK *
      (kYoloFacePreNmsTopK / 64) * sizeof(std::uint64_t)));
  view.sort_temporary_size = sort_temporary_bytes(batch_size);
  view.sort_temporary = take(view.sort_temporary_size);
  return view;
}

}  // namespace

cudaError_t launch_yolo_face_decode(const float *head_stride8, const float *head_stride16,
                                    const float *head_stride32, int batch_size,
                                    float confidence_threshold, FaceCandidate *candidates,
                                    cudaStream_t stream) {
  if (head_stride8 == nullptr || head_stride16 == nullptr || head_stride32 == nullptr ||
      candidates == nullptr || batch_size <= 0) {
    return cudaErrorInvalidValue;
  }
  constexpr int kThreads = 256;
  const int total = batch_size * kYoloFaceAnchorCount;
  const int blocks = (total + kThreads - 1) / kThreads;
  decode_kernel<<<blocks, kThreads, 0, stream>>>(head_stride8, head_stride16, head_stride32,
                                                 batch_size, confidence_threshold, candidates,
                                                 nullptr, nullptr);
  return cudaPeekAtLastError();
}

std::size_t yolo_face_workspace_size(int batch_size) {
  if (batch_size <= 0) {
    return 0;
  }
  const std::size_t item_count = static_cast<std::size_t>(batch_size) * kYoloFaceAnchorCount;
  std::size_t bytes = 0;
  bytes += align_up(item_count * sizeof(FaceCandidate));
  bytes += align_up(item_count * sizeof(float)) * 2;
  bytes += align_up(item_count * sizeof(int)) * 2;
  bytes += align_up(batch_size * sizeof(int)) * 2;
  bytes += align_up(static_cast<std::size_t>(batch_size) * kYoloFacePreNmsTopK *
                    (kYoloFacePreNmsTopK / 64) * sizeof(std::uint64_t));
  bytes += align_up(sort_temporary_bytes(batch_size));
  return bytes;
}

cudaError_t launch_yolo_face_postprocess(
    const float *head_stride8, const float *head_stride16, const float *head_stride32,
    int batch_size, float confidence_threshold, float iou_threshold, void *workspace,
    std::size_t workspace_bytes, const YoloFaceOutput &output, cudaStream_t stream) {
  if (workspace == nullptr || workspace_bytes < yolo_face_workspace_size(batch_size) ||
      output.num_detections == nullptr || output.boxes == nullptr || output.scores == nullptr ||
      output.landmarks_xy == nullptr) {
    return cudaErrorInvalidValue;
  }

  WorkspaceView view = partition_workspace(workspace, batch_size);
  constexpr int kThreads = 256;
  const int total = batch_size * kYoloFaceAnchorCount;
  decode_kernel<<<(total + kThreads - 1) / kThreads, kThreads, 0, stream>>>(
      head_stride8, head_stride16, head_stride32, batch_size, confidence_threshold,
      view.candidates, view.scores_in, view.indices_in);
  initialize_segments_kernel<<<(batch_size + kThreads - 1) / kThreads, kThreads, 0, stream>>>(
      batch_size, view.begin_offsets, view.end_offsets);

  cudaError_t status = cub::DeviceSegmentedRadixSort::SortPairsDescending(
      view.sort_temporary, view.sort_temporary_size, view.scores_in, view.scores_out,
      view.indices_in, view.indices_out, total, batch_size, view.begin_offsets, view.end_offsets, 0,
      sizeof(float) * 8, stream);
  if (status != cudaSuccess) {
    return status;
  }

  constexpr int kMaskBlocks = kYoloFacePreNmsTopK / 64;
  const dim3 nms_grid(kMaskBlocks, kMaskBlocks, batch_size);
  nms_mask_kernel<<<nms_grid, 64, 0, stream>>>(view.candidates, view.scores_out,
                                               view.indices_out, batch_size, iou_threshold,
                                               view.masks);
  select_detections_kernel<<<batch_size, 1, 0, stream>>>(
      view.candidates, view.scores_out, view.indices_out, confidence_threshold, view.masks, output);
  return cudaPeekAtLastError();
}

}  // namespace mvision
