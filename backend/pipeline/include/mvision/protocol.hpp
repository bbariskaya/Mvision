#pragma once

#include <array>
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

struct FaceOutput {
  std::uint32_t ordinal;
  float x;
  float y;
  float width;
  float height;
  std::array<float, 10> landmarks_xy;
  float detector_confidence;
  std::array<float, 512> embedding;
  std::vector<std::uint8_t> aligned_jpeg;
};

struct ImageResult {
  std::string request_id;
  std::string status;
  std::string error_code;
  std::vector<FaceOutput> faces;
};

class ProtocolError final : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

std::vector<std::uint8_t> encode_request(const ImageRequest &request);
ImageRequest decode_request(const std::vector<std::uint8_t> &frame);
std::vector<std::uint8_t> encode_result(const ImageResult &result);
ImageResult decode_result(const std::vector<std::uint8_t> &frame);

}  // namespace mvision
