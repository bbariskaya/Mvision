#pragma once

#include <nvdsinfer_custom_impl.h>

#include <vector>

extern "C" bool NvDsInferParseCustomYoloFace(
    const std::vector<NvDsInferLayerInfo> &output_layers,
    const NvDsInferNetworkInfo &network_info,
    const NvDsInferParseDetectionParams &detection_params,
    std::vector<NvDsInferInstanceMaskInfo> &objects);
