#pragma once

#include <NvInfer.h>

#include <cstddef>
#include <string>
#include <vector>

namespace mvision {

class YoloFacePostprocessPlugin final : public nvinfer1::IPluginV2DynamicExt {
 public:
  YoloFacePostprocessPlugin(float confidence_threshold, float iou_threshold);
  YoloFacePostprocessPlugin(const void *data, std::size_t length);

  const char *getPluginType() const noexcept override;
  const char *getPluginVersion() const noexcept override;
  int getNbOutputs() const noexcept override;
  int initialize() noexcept override;
  void terminate() noexcept override;
  std::size_t getSerializationSize() const noexcept override;
  void serialize(void *buffer) const noexcept override;
  void destroy() noexcept override;
  YoloFacePostprocessPlugin *clone() const noexcept override;
  void setPluginNamespace(const char *plugin_namespace) noexcept override;
  const char *getPluginNamespace() const noexcept override;
  nvinfer1::DataType getOutputDataType(int index, const nvinfer1::DataType *input_types,
                                       int input_count) const noexcept override;
  nvinfer1::DimsExprs getOutputDimensions(int output_index, const nvinfer1::DimsExprs *inputs,
                                          int input_count,
                                          nvinfer1::IExprBuilder &builder) noexcept override;
  bool supportsFormatCombination(int position, const nvinfer1::PluginTensorDesc *in_out,
                                 int input_count, int output_count) noexcept override;
  void configurePlugin(const nvinfer1::DynamicPluginTensorDesc *inputs, int input_count,
                       const nvinfer1::DynamicPluginTensorDesc *outputs,
                       int output_count) noexcept override;
  std::size_t getWorkspaceSize(const nvinfer1::PluginTensorDesc *inputs, int input_count,
                               const nvinfer1::PluginTensorDesc *outputs,
                               int output_count) const noexcept override;
  int enqueue(const nvinfer1::PluginTensorDesc *input_desc,
              const nvinfer1::PluginTensorDesc *output_desc, const void *const *inputs,
              void *const *outputs, void *workspace, cudaStream_t stream) noexcept override;
  void attachToContext(cudnnContext *cudnn, cublasContext *cublas,
                       nvinfer1::IGpuAllocator *allocator) noexcept override;
  void detachFromContext() noexcept override;

 private:
  float confidence_threshold_;
  float iou_threshold_;
  std::string namespace_;
};

class YoloFacePostprocessCreator final : public nvinfer1::IPluginCreator {
 public:
  YoloFacePostprocessCreator();

  const char *getPluginName() const noexcept override;
  const char *getPluginVersion() const noexcept override;
  const nvinfer1::PluginFieldCollection *getFieldNames() noexcept override;
  nvinfer1::IPluginV2 *createPlugin(const char *name,
                                    const nvinfer1::PluginFieldCollection *fields) noexcept override;
  nvinfer1::IPluginV2 *deserializePlugin(const char *name, const void *serial_data,
                                         std::size_t serial_length) noexcept override;
  void setPluginNamespace(const char *plugin_namespace) noexcept override;
  const char *getPluginNamespace() const noexcept override;

 private:
  std::string namespace_;
  std::vector<nvinfer1::PluginField> fields_;
  nvinfer1::PluginFieldCollection field_collection_{};
};

}  // namespace mvision
