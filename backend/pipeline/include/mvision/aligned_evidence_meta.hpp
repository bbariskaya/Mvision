#pragma once

#include <nvdsmeta.h>

#include <cstdint>
#include <vector>

namespace mvision {

struct AlignedJpegMeta {
  std::vector<std::uint8_t> bytes;
};

inline NvDsMetaType aligned_jpeg_meta_type() {
  static const NvDsMetaType type =
      nvds_get_user_meta_type(const_cast<char *>("MVISION.ALIGNED_JPEG"));
  return type;
}

}  // namespace mvision
