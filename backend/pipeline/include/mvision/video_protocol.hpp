#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace mvision {

inline constexpr std::uint32_t kVideoProtocolVersion = 1;
inline constexpr std::uint32_t kMaxVideoEventBytes = 64U * 1024U * 1024U;

struct VideoDetection {
  std::uint64_t frame;
  double timestamp;
  float x;
  float y;
  float width;
  float height;
  float detector_confidence;
  std::array<float, 10> landmarks{};
};

struct VideoProgress {
  std::uint64_t decoded_frame;
  std::uint64_t processed_frames;
  std::uint64_t total_frames;
  float progress_percent;
};

struct VideoTrackOutput {
  std::uint64_t tracker_id{};
  std::array<float, 512> embedding{};
  std::vector<std::uint8_t> representative_jpeg;
  std::vector<VideoDetection> detections;
};

struct VideoCompleted {
  std::uint64_t decoded_frames;
  std::uint64_t processed_frames;
  std::uint64_t track_count;
};

struct VideoFailed {
  std::string error_code;
  std::string message;
};

std::vector<std::uint8_t> encode_video_event(const VideoProgress& event);
std::vector<std::uint8_t> encode_video_event(const VideoTrackOutput& event);
std::vector<std::uint8_t> encode_video_event(const VideoCompleted& event);
std::vector<std::uint8_t> encode_video_event(const VideoFailed& event);

}  // namespace mvision
