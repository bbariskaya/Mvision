#include "mvision/yolo_face_parser.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace {

constexpr int kMaxDetections = 100;
constexpr int kLandmarkCoordinates = 10;
constexpr int kLandmarkMaskValues = 15;

const NvDsInferLayerInfo *find_layer(const std::vector<NvDsInferLayerInfo> &layers,
                                     const char *name, NvDsInferDataType type) {
  const auto match = std::find_if(layers.begin(), layers.end(), [name, type](const auto &layer) {
    return layer.layerName != nullptr && std::strcmp(layer.layerName, name) == 0 &&
           layer.dataType == type && layer.buffer != nullptr;
  });
  return match == layers.end() ? nullptr : &*match;
}

bool has_dimensions(const NvDsInferLayerInfo &layer,
                    std::initializer_list<unsigned int> dimensions) {
  if (layer.inferDims.numDims != dimensions.size()) {
    return false;
  }
  std::size_t index = 0;
  for (const unsigned int dimension : dimensions) {
    if (layer.inferDims.d[index++] != dimension) {
      return false;
    }
  }
  return true;
}

void release_masks(std::vector<NvDsInferInstanceMaskInfo> &objects) {
  for (auto &object : objects) {
    delete[] object.mask;
    object.mask = nullptr;
  }
  objects.clear();
}

}  // namespace

extern "C" bool NvDsInferParseCustomYoloFace(
    const std::vector<NvDsInferLayerInfo> &output_layers,
    const NvDsInferNetworkInfo &network_info,
    const NvDsInferParseDetectionParams &detection_params,
    std::vector<NvDsInferInstanceMaskInfo> &objects) {
  const auto *count_layer = find_layer(output_layers, "num_dets", INT32);
  const auto *boxes_layer = find_layer(output_layers, "boxes", FLOAT);
  const auto *scores_layer = find_layer(output_layers, "scores", FLOAT);
  const auto *landmarks_layer = find_layer(output_layers, "landmarks", FLOAT);
  if (count_layer == nullptr || boxes_layer == nullptr || scores_layer == nullptr ||
      landmarks_layer == nullptr || !has_dimensions(*count_layer, {1}) ||
      !has_dimensions(*boxes_layer, {kMaxDetections, 4}) ||
      !has_dimensions(*scores_layer, {kMaxDetections}) ||
      !has_dimensions(*landmarks_layer, {kMaxDetections, kLandmarkCoordinates})) {
    return false;
  }

  const int detection_count = *static_cast<const std::int32_t *>(count_layer->buffer);
  if (detection_count < 0 || detection_count > kMaxDetections || network_info.width == 0 ||
      network_info.height == 0) {
    return false;
  }

  const auto *boxes = static_cast<const float *>(boxes_layer->buffer);
  const auto *scores = static_cast<const float *>(scores_layer->buffer);
  const auto *landmarks = static_cast<const float *>(landmarks_layer->buffer);
  const float threshold = detection_params.perClassPreclusterThreshold.empty()
                              ? 0.0F
                              : detection_params.perClassPreclusterThreshold[0];
  objects.clear();
  objects.reserve(detection_count);

  for (int index = 0; index < detection_count; ++index) {
    const float score = scores[index];
    const float x1 = std::clamp(boxes[index * 4], 0.0F, static_cast<float>(network_info.width));
    const float y1 =
        std::clamp(boxes[index * 4 + 1], 0.0F, static_cast<float>(network_info.height));
    const float x2 =
        std::clamp(boxes[index * 4 + 2], 0.0F, static_cast<float>(network_info.width));
    const float y2 =
        std::clamp(boxes[index * 4 + 3], 0.0F, static_cast<float>(network_info.height));
    if (!std::isfinite(score) || !std::isfinite(x1) || !std::isfinite(y1) ||
        !std::isfinite(x2) || !std::isfinite(y2) || score < threshold || x2 <= x1 || y2 <= y1) {
      continue;
    }

    NvDsInferInstanceMaskInfo object{};
    object.classId = 0;
    object.left = x1;
    object.top = y1;
    object.width = x2 - x1;
    object.height = y2 - y1;
    object.detectionConfidence = score;
    object.mask = new (std::nothrow) float[kLandmarkMaskValues];
    if (object.mask == nullptr) {
      release_masks(objects);
      return false;
    }
    for (int landmark = 0; landmark < 5; ++landmark) {
      const float x = landmarks[index * kLandmarkCoordinates + landmark * 2];
      const float y = landmarks[index * kLandmarkCoordinates + landmark * 2 + 1];
      object.mask[landmark * 3] =
          std::clamp(x, 0.0F, static_cast<float>(network_info.width));
      object.mask[landmark * 3 + 1] =
          std::clamp(y, 0.0F, static_cast<float>(network_info.height));
      object.mask[landmark * 3 + 2] = 1.0F;
    }
    object.mask_width = network_info.width;
    object.mask_height = network_info.height;
    object.mask_size = kLandmarkMaskValues * sizeof(float);
    objects.push_back(object);
  }
  return true;
}

CHECK_CUSTOM_INSTANCE_MASK_PARSE_FUNC_PROTOTYPE(NvDsInferParseCustomYoloFace);
