#include "mvision/video_protocol.hpp"

#include <arpa/inet.h>
#include <msgpack.hpp>

#include <cmath>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

namespace mvision {
namespace {

void require_finite(double value) {
  if (!std::isfinite(value)) {
    throw std::invalid_argument("video event contains a non-finite value");
  }
}

std::vector<std::uint8_t> frame_payload(const msgpack::sbuffer& payload) {
  if (payload.size() > kMaxVideoEventBytes) {
    throw std::length_error("video event exceeds maximum frame size");
  }
  const auto payload_size = static_cast<std::uint32_t>(payload.size());
  const auto network_size = htonl(payload_size);
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload.size());
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  std::memcpy(frame.data() + sizeof(network_size), payload.data(), payload.size());
  return frame;
}

template <typename WriteFields>
std::vector<std::uint8_t> pack_event(const char* event_type, std::uint32_t field_count,
                                     WriteFields write_fields) {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  packer.pack_map(field_count + 2);
  packer.pack(std::string("protocol_version"));
  packer.pack(kVideoProtocolVersion);
  packer.pack(std::string("event_type"));
  packer.pack(std::string(event_type));
  write_fields(packer);
  return frame_payload(payload);
}

}  // namespace

std::vector<std::uint8_t> encode_video_event(const VideoProgress& event) {
  require_finite(event.progress_percent);
  if (event.progress_percent < 0.0F || event.progress_percent > 100.0F) {
    throw std::invalid_argument("video progress is outside 0..100");
  }
  return pack_event("progress", 4, [&](auto& packer) {
    packer.pack(std::string("decoded_frame"));
    packer.pack(event.decoded_frame);
    packer.pack(std::string("processed_frames"));
    packer.pack(event.processed_frames);
    packer.pack(std::string("total_frames"));
    packer.pack(event.total_frames);
    packer.pack(std::string("progress_percent"));
    packer.pack(event.progress_percent);
  });
}

std::vector<std::uint8_t> encode_video_event(const VideoTrackOutput& event) {
  for (const float value : event.embedding) {
    require_finite(value);
  }
  for (const auto& detection : event.detections) {
    require_finite(detection.timestamp);
    require_finite(detection.x);
    require_finite(detection.y);
    require_finite(detection.width);
    require_finite(detection.height);
    require_finite(detection.detector_confidence);
    for (const float value : detection.landmarks) {
      require_finite(value);
    }
  }
  return pack_event("track", 4, [&](auto& packer) {
    packer.pack(std::string("tracker_id"));
    packer.pack(event.tracker_id);
    packer.pack(std::string("embedding"));
    packer.pack(event.embedding);
    packer.pack(std::string("representative_jpeg"));
    packer.pack_bin(static_cast<std::uint32_t>(event.representative_jpeg.size()));
    packer.pack_bin_body(reinterpret_cast<const char*>(event.representative_jpeg.data()),
                         static_cast<std::uint32_t>(event.representative_jpeg.size()));
    packer.pack(std::string("detections"));
    packer.pack_array(static_cast<std::uint32_t>(event.detections.size()));
    for (const auto& detection : event.detections) {
      packer.pack_map(8);
      packer.pack(std::string("frame"));
      packer.pack(detection.frame);
      packer.pack(std::string("timestamp"));
      packer.pack(detection.timestamp);
      packer.pack(std::string("x"));
      packer.pack(detection.x);
      packer.pack(std::string("y"));
      packer.pack(detection.y);
      packer.pack(std::string("width"));
      packer.pack(detection.width);
      packer.pack(std::string("height"));
      packer.pack(detection.height);
      packer.pack(std::string("detector_confidence"));
      packer.pack(detection.detector_confidence);
      packer.pack(std::string("landmarks"));
      packer.pack(detection.landmarks);
    }
  });
}

std::vector<std::uint8_t> encode_video_event(const VideoCompleted& event) {
  return pack_event("completed", 3, [&](auto& packer) {
    packer.pack(std::string("decoded_frames"));
    packer.pack(event.decoded_frames);
    packer.pack(std::string("processed_frames"));
    packer.pack(event.processed_frames);
    packer.pack(std::string("track_count"));
    packer.pack(event.track_count);
  });
}

std::vector<std::uint8_t> encode_video_event(const VideoFailed& event) {
  return pack_event("failed", 2, [&](auto& packer) {
    packer.pack(std::string("error_code"));
    packer.pack(event.error_code);
    packer.pack(std::string("message"));
    packer.pack(event.message);
  });
}

}  // namespace mvision
