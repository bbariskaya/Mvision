#include "mvision/yolo_postprocess_plugin.hpp"

#include "mvision/yolo_postprocess.hpp"

#include <NvInferPlugin.h>

#include <cstring>
#include <new>
#include <string>

namespace mvision {
namespace {

constexpr char kPluginName[] = "MvisionYoloFacePostprocess";
constexpr char kPluginVersion[] = "1";

}  // namespace

YoloFacePostprocessPlugin::YoloFacePostprocessPlugin(float confidence_threshold,
                                                     float iou_threshold)
    : confidence_threshold_(confidence_threshold), iou_threshold_(iou_threshold) {}

YoloFacePostprocessPlugin::YoloFacePostprocessPlugin(const void *data, std::size_t length)
    : confidence_threshold_(0.25F), iou_threshold_(0.45F) {
  if (length == sizeof(float) * 2) {
    std::memcpy(&confidence_threshold_, data, sizeof(float));
    std::memcpy(&iou_threshold_, static_cast<const char *>(data) + sizeof(float), sizeof(float));
  }
}

const char *YoloFacePostprocessPlugin::getPluginType() const noexcept { return kPluginName; }
const char *YoloFacePostprocessPlugin::getPluginVersion() const noexcept { return kPluginVersion; }
int YoloFacePostprocessPlugin::getNbOutputs() const noexcept { return 4; }
int YoloFacePostprocessPlugin::initialize() noexcept { return 0; }
void YoloFacePostprocessPlugin::terminate() noexcept {}
std::size_t YoloFacePostprocessPlugin::getSerializationSize() const noexcept {
  return sizeof(float) * 2;
}
void YoloFacePostprocessPlugin::serialize(void *buffer) const noexcept {
  std::memcpy(buffer, &confidence_threshold_, sizeof(float));
  std::memcpy(static_cast<char *>(buffer) + sizeof(float), &iou_threshold_, sizeof(float));
}
void YoloFacePostprocessPlugin::destroy() noexcept { delete this; }
YoloFacePostprocessPlugin *YoloFacePostprocessPlugin::clone() const noexcept {
  auto *plugin = new (std::nothrow)
      YoloFacePostprocessPlugin(confidence_threshold_, iou_threshold_);
  if (plugin != nullptr) {
    plugin->setPluginNamespace(namespace_.c_str());
  }
  return plugin;
}
void YoloFacePostprocessPlugin::setPluginNamespace(const char *plugin_namespace) noexcept {
  namespace_ = plugin_namespace == nullptr ? "" : plugin_namespace;
}
const char *YoloFacePostprocessPlugin::getPluginNamespace() const noexcept {
  return namespace_.c_str();
}
nvinfer1::DataType YoloFacePostprocessPlugin::getOutputDataType(
    int index, const nvinfer1::DataType *, int) const noexcept {
  return index == 0 ? nvinfer1::DataType::kINT32 : nvinfer1::DataType::kFLOAT;
}
nvinfer1::DimsExprs YoloFacePostprocessPlugin::getOutputDimensions(
    int output_index, const nvinfer1::DimsExprs *inputs, int,
    nvinfer1::IExprBuilder &builder) noexcept {
  nvinfer1::DimsExprs output{};
  if (output_index == 0) {
    output.nbDims = 1;
    output.d[0] = inputs[0].d[0];
  } else if (output_index == 1) {
    output.nbDims = 3;
    output.d[0] = inputs[0].d[0];
    output.d[1] = builder.constant(kYoloFaceMaxDetections);
    output.d[2] = builder.constant(4);
  } else {
    output.nbDims = 2 + (output_index == 3 ? 1 : 0);
    output.d[0] = inputs[0].d[0];
    output.d[1] = builder.constant(kYoloFaceMaxDetections);
    if (output_index == 3) {
      output.d[2] = builder.constant(10);
    }
  }
  return output;
}
bool YoloFacePostprocessPlugin::supportsFormatCombination(
    int position, const nvinfer1::PluginTensorDesc *in_out, int input_count,
    int) noexcept {
  if (in_out[position].format != nvinfer1::TensorFormat::kLINEAR) {
    return false;
  }
  if (position < input_count) {
    return in_out[position].type == nvinfer1::DataType::kFLOAT;
  }
  return in_out[position].type ==
         (position == input_count ? nvinfer1::DataType::kINT32 : nvinfer1::DataType::kFLOAT);
}
void YoloFacePostprocessPlugin::configurePlugin(const nvinfer1::DynamicPluginTensorDesc *, int,
                                                const nvinfer1::DynamicPluginTensorDesc *,
                                                int) noexcept {}
std::size_t YoloFacePostprocessPlugin::getWorkspaceSize(
    const nvinfer1::PluginTensorDesc *inputs, int, const nvinfer1::PluginTensorDesc *,
    int) const noexcept {
  return yolo_face_workspace_size(inputs[0].dims.d[0]);
}
int YoloFacePostprocessPlugin::enqueue(const nvinfer1::PluginTensorDesc *input_desc,
                                       const nvinfer1::PluginTensorDesc *,
                                       const void *const *inputs, void *const *outputs,
                                       void *workspace, cudaStream_t stream) noexcept {
  const int batch_size = input_desc[0].dims.d[0];
  const YoloFaceOutput output{static_cast<int *>(outputs[0]), static_cast<float *>(outputs[1]),
                              static_cast<float *>(outputs[2]),
                              static_cast<float *>(outputs[3])};
  const cudaError_t status = launch_yolo_face_postprocess(
      static_cast<const float *>(inputs[0]), static_cast<const float *>(inputs[1]),
      static_cast<const float *>(inputs[2]), batch_size, confidence_threshold_, iou_threshold_,
      workspace, yolo_face_workspace_size(batch_size), output, stream);
  return status == cudaSuccess ? 0 : 1;
}
void YoloFacePostprocessPlugin::attachToContext(cudnnContext *, cublasContext *,
                                                nvinfer1::IGpuAllocator *) noexcept {}
void YoloFacePostprocessPlugin::detachFromContext() noexcept {}

YoloFacePostprocessCreator::YoloFacePostprocessCreator() {
  fields_.emplace_back(nvinfer1::PluginField{"confidence_threshold", nullptr,
                                             nvinfer1::PluginFieldType::kFLOAT32, 1});
  fields_.emplace_back(
      nvinfer1::PluginField{"iou_threshold", nullptr, nvinfer1::PluginFieldType::kFLOAT32, 1});
  field_collection_.nbFields = static_cast<int>(fields_.size());
  field_collection_.fields = fields_.data();
}
const char *YoloFacePostprocessCreator::getPluginName() const noexcept { return kPluginName; }
const char *YoloFacePostprocessCreator::getPluginVersion() const noexcept {
  return kPluginVersion;
}
const nvinfer1::PluginFieldCollection *YoloFacePostprocessCreator::getFieldNames() noexcept {
  return &field_collection_;
}
nvinfer1::IPluginV2 *YoloFacePostprocessCreator::createPlugin(
    const char *, const nvinfer1::PluginFieldCollection *fields) noexcept {
  float confidence = 0.25F;
  float iou = 0.45F;
  if (fields != nullptr) {
    for (int index = 0; index < fields->nbFields; ++index) {
      const auto &field = fields->fields[index];
      if (field.data == nullptr) {
        continue;
      }
      if (std::string(field.name) == "confidence_threshold") {
        confidence = *static_cast<const float *>(field.data);
      } else if (std::string(field.name) == "iou_threshold") {
        iou = *static_cast<const float *>(field.data);
      }
    }
  }
  auto *plugin = new (std::nothrow) YoloFacePostprocessPlugin(confidence, iou);
  if (plugin != nullptr) {
    plugin->setPluginNamespace(namespace_.c_str());
  }
  return plugin;
}
nvinfer1::IPluginV2 *YoloFacePostprocessCreator::deserializePlugin(
    const char *, const void *serial_data, std::size_t serial_length) noexcept {
  auto *plugin = new (std::nothrow) YoloFacePostprocessPlugin(serial_data, serial_length);
  if (plugin != nullptr) {
    plugin->setPluginNamespace(namespace_.c_str());
  }
  return plugin;
}
void YoloFacePostprocessCreator::setPluginNamespace(const char *plugin_namespace) noexcept {
  namespace_ = plugin_namespace == nullptr ? "" : plugin_namespace;
}
const char *YoloFacePostprocessCreator::getPluginNamespace() const noexcept {
  return namespace_.c_str();
}

REGISTER_TENSORRT_PLUGIN(YoloFacePostprocessCreator);

}  // namespace mvision
