#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace mvision {

inline constexpr std::uint32_t kProtocolVersion = 1;
inline constexpr std::uint32_t kMaxUploadBytes = 10U * 1024U * 1024U;
inline constexpr std::uint32_t kMaxFrameBytes = kMaxUploadBytes + 16U * 1024U * 1024U;

struct ImageRequest {
  std::string request_id;
  std::vector<std::uint8_t> encoded_jpeg;
};

class ProtocolError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

std::vector<std::uint8_t> encode_request(const ImageRequest &request);
ImageRequest decode_request(const std::vector<std::uint8_t> &frame);

}  // namespace mvision
