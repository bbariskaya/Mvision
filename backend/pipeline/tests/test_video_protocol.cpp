#include "mvision/video_protocol.hpp"

#include <arpa/inet.h>
#include <msgpack.hpp>

#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                  \
  do {                                                                     \
    if (!(condition)) throw std::runtime_error("assertion failed: " #condition); \
  } while (false)
#endif

namespace {

msgpack::object_handle unpack_frame(const std::vector<std::uint8_t>& frame) {
  assert(frame.size() >= sizeof(std::uint32_t));
  std::uint32_t network_size = 0;
  std::memcpy(&network_size, frame.data(), sizeof(network_size));
  const auto payload_size = ntohl(network_size);
  assert(payload_size == frame.size() - sizeof(network_size));
  return msgpack::unpack(reinterpret_cast<const char*>(frame.data() + sizeof(network_size)),
                         payload_size);
}

std::string event_type(const std::vector<std::uint8_t>& frame) {
  auto handle = unpack_frame(frame);
  const auto map = handle.get().as<std::map<std::string, msgpack::object>>();
  return map.at("event_type").as<std::string>();
}

}  // namespace

int main() {
  mvision::VideoProgress progress{10, 2, 20, 50.0F};
  assert(event_type(mvision::encode_video_event(progress)) == "progress");

  mvision::VideoTrackOutput track;
  track.tracker_id = 42;
  track.embedding.fill(0.0F);
  track.embedding[0] = 1.0F;
  track.representative_jpeg = {0xFF, 0xD8, 0xFF, 0xD9};
  track.detections.push_back({5, 0.2, 1.0F, 2.0F, 3.0F, 4.0F, 0.9F});
  track.detections[0].landmarks = {1.0F, 2.0F, 3.0F, 4.0F, 5.0F,
                                    6.0F, 7.0F, 8.0F, 9.0F, 10.0F};
  const auto encoded_track = mvision::encode_video_event(track);
  assert(event_type(encoded_track) == "track");
  auto track_handle = unpack_frame(encoded_track);
  const auto track_map =
      track_handle.get().as<std::map<std::string, msgpack::object>>();
  const auto detections =
      track_map.at("detections").as<std::vector<std::map<std::string, msgpack::object>>>();
  assert(detections[0].at("landmarks").as<std::vector<float>>().size() == 10);

  mvision::VideoCompleted completed{100, 20, 2};
  assert(event_type(mvision::encode_video_event(completed)) == "completed");

  mvision::VideoFailed failed{"VIDEO_PIPELINE_ERROR", "pipeline failed"};
  assert(event_type(mvision::encode_video_event(failed)) == "failed");
  return 0;
}
