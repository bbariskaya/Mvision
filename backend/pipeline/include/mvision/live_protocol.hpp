#pragma once

#include "mvision/live_track_state.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace mvision {

inline constexpr std::uint32_t kLiveProtocolVersion = 1;
inline constexpr std::uint32_t kMaxLiveFrameBytes = 4U * 1024U * 1024U;
inline constexpr std::size_t kMaxAlignedJpegBytes = 512U * 1024U;
inline constexpr std::size_t kMaxLiveObservations = 10U;

struct ProtocolHeader {
  std::uint32_t protocol_version;
  std::string message_type;
  std::string camera_id;
  std::string run_id;
  std::uint64_t generation;
  std::uint64_t sequence;
  std::string traceparent;
  std::optional<std::string> tracestate;
};

struct StartCommand {
  ProtocolHeader header;
  std::string uri;
  std::uint32_t gpu_id;
  std::string pgie_config_path;
  std::string preprocess_config_path;
  std::string sgie_config_path;
  std::string tracker_config_path;
  std::string output_mount_path;
  std::uint16_t output_udp_port;
  std::uint16_t output_rtsp_port;
  std::uint32_t latency_ms;
  std::uint32_t reconnect_interval_seconds;
  std::int32_t reconnect_attempts;
  std::uint64_t frame_timeout_ns;
};

struct IdentityAssignment {
  ProtocolHeader header;
  std::uint64_t tracker_id;
  std::uint64_t assignment_revision;
  std::uint64_t identity_epoch;
  std::string identity_state;
  std::optional<std::string> display_name;
  std::optional<std::string> face_id;
  std::optional<float> match_score;
  std::optional<float> recognition_threshold;
  std::optional<std::array<float, 512>> reference_embedding;
  std::uint64_t decision_sequence;
};

struct StopCommand {
  ProtocolHeader header;
  std::string reason;
  std::uint64_t shutdown_deadline_ns;
};

struct HelloEvent {
  ProtocolHeader header;
  std::string build_id;
  std::string gstreamer_version;
  std::string deepstream_version;
};

struct StateEvent {
  ProtocolHeader header;
  std::string state;
  std::optional<std::string> reason;
};

struct OutputReadyEvent {
  ProtocolHeader header;
  std::string mount_path;
  std::string codec;
  std::string caps;
};

struct TrackEvidenceEvent {
  ProtocolHeader header;
  std::uint64_t tracker_id;
  std::uint64_t evidence_revision;
  std::uint64_t first_seen_ns;
  std::uint64_t last_seen_ns;
  std::vector<LiveObservation> observations;
  std::vector<std::byte> representative_aligned_jpeg;
};

struct TrackExpiredEvent {
  ProtocolHeader header;
  std::uint64_t tracker_id;
  std::uint64_t evidence_revision;
  std::uint64_t first_seen_ns;
  std::uint64_t last_seen_ns;
  std::string reason;
};

struct MetricsEvent {
  ProtocolHeader header;
  std::map<std::string, std::uint64_t> counters;
  std::map<std::string, double> gauges;
};

struct FailedEvent {
  ProtocolHeader header;
  std::string error_code;
  std::string message;
};

struct StoppedEvent {
  ProtocolHeader header;
  std::uint64_t decoded_frames;
  std::uint64_t emitted_evidence;
  std::uint64_t dropped_events;
  bool clean_shutdown;
  std::string reason;
};

using NativeAttribute = std::variant<std::string, std::int64_t, double>;

struct NativeOperationEvent {
  ProtocolHeader header;
  std::string operation;
  std::uint64_t started_monotonic_ns;
  std::uint64_t ended_monotonic_ns;
  std::string status;
  std::optional<std::string> error_code;
  std::map<std::string, NativeAttribute> attributes;
};

using LiveMessage =
    std::variant<StartCommand, IdentityAssignment, StopCommand, HelloEvent,
                 StateEvent, OutputReadyEvent, TrackEvidenceEvent,
                 TrackExpiredEvent, MetricsEvent, FailedEvent, StoppedEvent,
                 NativeOperationEvent>;

class LiveProtocolError : public std::runtime_error {
 public:
  explicit LiveProtocolError(std::string code);
  const std::string& code() const noexcept;

 private:
  std::string code_;
};

struct DecodeContext {
  std::string camera_id;
  std::string run_id;
  std::uint64_t generation;
  std::unordered_map<std::uint64_t, std::uint64_t> assignment_revisions;
};

std::vector<std::uint8_t> encode_live_message(const LiveMessage& message);
LiveMessage decode_live_message(const std::vector<std::uint8_t>& frame,
                                DecodeContext* context = nullptr);

}  // namespace mvision
