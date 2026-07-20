#include "mvision/yolo_face_parser.hpp"

#include <cmath>
#include <cstdint>
#include <vector>

namespace {

NvDsInferLayerInfo layer(const char *name, NvDsInferDataType type, void *buffer,
                         std::initializer_list<unsigned int> dimensions) {
  NvDsInferLayerInfo info{};
  info.layerName = name;
  info.dataType = type;
  info.buffer = buffer;
  info.inferDims.numDims = dimensions.size();
  std::size_t index = 0;
  for (const unsigned int dimension : dimensions) {
    info.inferDims.d[index++] = dimension;
  }
  return info;
}

bool near(float actual, float expected) { return std::abs(actual - expected) < 0.001F; }

}  // namespace

int main() {
  std::int32_t count = 2;
  std::vector<float> boxes(100 * 4, 0.0F);
  std::vector<float> scores(100, 0.0F);
  std::vector<float> landmarks(100 * 10, 0.0F);
  boxes[0] = 10.0F;
  boxes[1] = 20.0F;
  boxes[2] = 50.0F;
  boxes[3] = 70.0F;
  scores[0] = 0.9F;
  for (int coordinate = 0; coordinate < 10; ++coordinate) {
    landmarks[coordinate] = static_cast<float>(coordinate + 1);
  }
  boxes[4] = 100.0F;
  boxes[5] = 110.0F;
  boxes[6] = 150.0F;
  boxes[7] = 180.0F;
  scores[1] = 0.2F;

  const std::vector<NvDsInferLayerInfo> layers{
      layer("num_dets", INT32, &count, {1}),
      layer("boxes", FLOAT, boxes.data(), {100, 4}),
      layer("scores", FLOAT, scores.data(), {100}),
      layer("landmarks", FLOAT, landmarks.data(), {100, 10}),
  };
  NvDsInferNetworkInfo network{640, 640, 3};
  NvDsInferParseDetectionParams parameters{};
  parameters.numClassesConfigured = 1;
  parameters.perClassPreclusterThreshold = {0.25F};
  std::vector<NvDsInferInstanceMaskInfo> objects;

  const bool parsed = NvDsInferParseCustomYoloFace(layers, network, parameters, objects);
  if (!parsed || objects.size() != 1) {
    return 1;
  }
  const auto &face = objects[0];
  const bool valid = face.classId == 0 && near(face.left, 10.0F) && near(face.top, 20.0F) &&
                     near(face.width, 40.0F) && near(face.height, 50.0F) &&
                     near(face.detectionConfidence, 0.9F) && face.mask != nullptr &&
                     face.mask_size == 15 * sizeof(float) && face.mask_width == 640 &&
                     face.mask_height == 640 && near(face.mask[0], 1.0F) &&
                     near(face.mask[1], 2.0F) && near(face.mask[2], 1.0F) &&
                     near(face.mask[12], 9.0F) && near(face.mask[13], 10.0F) &&
                     near(face.mask[14], 1.0F);
  delete[] face.mask;
  return valid ? 0 : 1;
}
