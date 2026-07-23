#include "mvision/live_protocol.hpp"

#include <arpa/inet.h>
#include <msgpack.hpp>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <regex>
#include <set>
#include <string_view>
#include <type_traits>
#include <utility>

namespace mvision {
namespace {

using ObjectMap = std::map<std::string, msgpack::object>;

[[noreturn]] void fail(const std::string& code) {
  throw LiveProtocolError(code);
}

const msgpack::object& required(const ObjectMap& values, std::string_view key) {
  const auto found = values.find(std::string(key));
  if (found == values.end()) fail("MISSING_FIELD");
  return found->second;
}

std::uint64_t unsigned_integer(const msgpack::object& value,
                               std::uint64_t minimum = 0) {
  if (value.type != msgpack::type::POSITIVE_INTEGER) fail("INVALID_INTEGER");
  const auto result = value.as<std::uint64_t>();
  if (result < minimum) fail("INVALID_INTEGER");
  return result;
}

std::int64_t signed_integer(const msgpack::object& value) {
  if (value.type != msgpack::type::POSITIVE_INTEGER &&
      value.type != msgpack::type::NEGATIVE_INTEGER) {
    fail("INVALID_INTEGER");
  }
  return value.as<std::int64_t>();
}

double finite_number(const msgpack::object& value) {
  if (value.type != msgpack::type::FLOAT32 &&
      value.type != msgpack::type::FLOAT64 &&
      value.type != msgpack::type::POSITIVE_INTEGER &&
      value.type != msgpack::type::NEGATIVE_INTEGER) {
    fail("NON_FINITE_VALUE");
  }
  const auto result = value.as<double>();
  if (!std::isfinite(result)) fail("NON_FINITE_VALUE");
  return result;
}

std::string string_value(const msgpack::object& value) {
  if (value.type != msgpack::type::STR) fail("INVALID_PAYLOAD");
  return value.as<std::string>();
}

std::optional<std::string> optional_string(const msgpack::object& value) {
  if (value.type == msgpack::type::NIL) return std::nullopt;
  return string_value(value);
}

std::optional<float> optional_float(const msgpack::object& value) {
  if (value.type == msgpack::type::NIL) return std::nullopt;
  return static_cast<float>(finite_number(value));
}

bool canonical_uuid(const std::string& value) {
  if (value.size() != 36) return false;
  constexpr std::array<std::size_t, 4> hyphens{8, 13, 18, 23};
  for (std::size_t index = 0; index < value.size(); ++index) {
    if (std::find(hyphens.begin(), hyphens.end(), index) != hyphens.end()) {
      if (value[index] != '-') return false;
      continue;
    }
    const auto ch = value[index];
    const bool hexadecimal = (ch >= '0' && ch <= '9') ||
                             (ch >= 'a' && ch <= 'f') ||
                             (ch >= 'A' && ch <= 'F');
    if (!hexadecimal) return false;
  }
  return true;
}

std::string uuid_value(const msgpack::object& value) {
  const auto result = string_value(value);
  if (!canonical_uuid(result)) fail("INVALID_UUID");
  return result;
}

void validate_trace_context(const std::string& traceparent,
                            const std::optional<std::string>& tracestate) {
  static const std::regex pattern(
      "^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$");
  std::smatch match;
  if (!std::regex_match(traceparent, match, pattern) ||
      match[1].str() == std::string(32, '0') ||
      match[2].str() == std::string(16, '0')) {
    fail("INVALID_TRACE_CONTEXT");
  }
  if (!tracestate.has_value()) return;
  if (tracestate->size() > 512) fail("INVALID_TRACE_CONTEXT");
  std::size_t members = 1;
  std::size_t member_start = 0;
  for (std::size_t index = 0; index <= tracestate->size(); ++index) {
    if (index < tracestate->size()) {
      const auto character = static_cast<unsigned char>((*tracestate)[index]);
      if (character < 0x20 || character > 0x7E) fail("INVALID_TRACE_CONTEXT");
    }
    if (index == tracestate->size() || (*tracestate)[index] == ',') {
      if (index == member_start) fail("INVALID_TRACE_CONTEXT");
      const auto member = tracestate->substr(member_start, index - member_start);
      if (member.front() == ' ' || member.back() == ' ' ||
          member.find('=') == std::string::npos) {
        fail("INVALID_TRACE_CONTEXT");
      }
      if (index < tracestate->size()) ++members;
      member_start = index + 1;
    }
  }
  if (members > 32) fail("INVALID_TRACE_CONTEXT");
}

template <std::size_t Size>
std::array<float, Size> float_array(const msgpack::object& value,
                                    const std::string& size_error) {
  if (value.type != msgpack::type::ARRAY || value.via.array.size != Size) {
    fail(size_error);
  }
  std::array<float, Size> result{};
  for (std::size_t index = 0; index < Size; ++index) {
    result[index] = static_cast<float>(finite_number(value.via.array.ptr[index]));
  }
  return result;
}

void validate_exact_fields(const ObjectMap& values,
                           const std::set<std::string>& expected) {
  for (const auto& key : expected) {
    if (values.find(key) == values.end()) fail("MISSING_FIELD");
  }
  for (const auto& [key, value] : values) {
    static_cast<void>(value);
    if (expected.find(key) == expected.end()) fail("UNKNOWN_FIELD");
  }
}

void validate_fields(const ObjectMap& values,
                     const std::set<std::string>& message_fields) {
  static const std::set<std::string> header_fields{
      "protocol_version", "message_type", "session_id", "camera_id",
      "run_id", "generation", "runtime_attempt", "sequence", "traceparent",
      "tracestate"};
  auto expected = header_fields;
  expected.insert(message_fields.begin(), message_fields.end());
  validate_exact_fields(values, expected);
}

ProtocolHeader decode_header(const ObjectMap& values) {
  const auto version = unsigned_integer(required(values, "protocol_version"), 1);
  if (version != kLiveProtocolVersion) fail("UNSUPPORTED_PROTOCOL_VERSION");
  const auto message_type = string_value(required(values, "message_type"));
  static const std::set<std::string> known_types{
      "start",          "identity_assignment", "stop",     "hello",
      "state",          "output_ready",         "track_evidence",
      "track_expired",  "metrics",              "failed", "stopped",
      "native_operation"};
  if (known_types.find(message_type) == known_types.end()) {
    fail("UNKNOWN_MESSAGE_TYPE");
  }
  const auto traceparent = string_value(required(values, "traceparent"));
  const auto tracestate = optional_string(required(values, "tracestate"));
  validate_trace_context(traceparent, tracestate);
  return {static_cast<std::uint32_t>(version),
          message_type,
          uuid_value(required(values, "session_id")),
          uuid_value(required(values, "camera_id")),
          uuid_value(required(values, "run_id")),
          unsigned_integer(required(values, "generation"), 1),
          unsigned_integer(required(values, "runtime_attempt"), 1),
          unsigned_integer(required(values, "sequence")), traceparent, tracestate};
}

LiveObservation decode_observation(const msgpack::object& value) {
  if (value.type != msgpack::type::MAP) fail("INVALID_PAYLOAD");
  const auto values = value.as<ObjectMap>();
  validate_exact_fields(values,
                        {"timestamp_ns", "bbox", "detector_confidence",
                         "landmarks", "landmark_confidences", "quality_score",
                         "reject_mask", "embedding"});
  LiveObservation result;
  result.timestamp_ns = unsigned_integer(required(values, "timestamp_ns"));
  result.bbox = float_array<4>(required(values, "bbox"), "INVALID_PAYLOAD");
  result.detector_confidence =
      static_cast<float>(finite_number(required(values, "detector_confidence")));
  result.landmarks =
      float_array<10>(required(values, "landmarks"), "INVALID_LANDMARKS");
  result.landmark_confidences = float_array<5>(
      required(values, "landmark_confidences"), "INVALID_LANDMARKS");
  result.quality.quality_score =
      static_cast<float>(finite_number(required(values, "quality_score")));
  result.quality.reject_mask = unsigned_integer(required(values, "reject_mask"));
  result.embedding =
      float_array<512>(required(values, "embedding"), "INVALID_EMBEDDING");
  double squared_norm = 0.0;
  for (const auto item : result.embedding) {
    squared_norm += static_cast<double>(item) * static_cast<double>(item);
  }
  const auto norm = std::sqrt(squared_norm);
  if (norm < 0.99 || norm > 1.01) fail("INVALID_EMBEDDING_NORM");
  return result;
}

template <typename Packer>
void pack_header(Packer& packer, const ProtocolHeader& header) {
  packer.pack(std::string("protocol_version"));
  packer.pack(header.protocol_version);
  packer.pack(std::string("message_type"));
  packer.pack(header.message_type);
  packer.pack(std::string("session_id"));
  packer.pack(header.session_id);
  packer.pack(std::string("camera_id"));
  packer.pack(header.camera_id);
  packer.pack(std::string("run_id"));
  packer.pack(header.run_id);
  packer.pack(std::string("generation"));
  packer.pack(header.generation);
  packer.pack(std::string("runtime_attempt"));
  packer.pack(header.runtime_attempt);
  packer.pack(std::string("sequence"));
  packer.pack(header.sequence);
  packer.pack(std::string("traceparent"));
  packer.pack(header.traceparent);
  packer.pack(std::string("tracestate"));
  if (header.tracestate.has_value()) {
    packer.pack(*header.tracestate);
  } else {
    packer.pack_nil();
  }
}

template <typename Packer, typename Value>
void pack_field(Packer& packer, const std::string& key, const Value& value) {
  packer.pack(key);
  packer.pack(value);
}

template <typename Packer, typename Value>
void pack_optional(Packer& packer, const std::string& key,
                   const std::optional<Value>& value) {
  packer.pack(key);
  if (value.has_value()) {
    packer.pack(*value);
  } else {
    packer.pack_nil();
  }
}

template <typename Packer, std::size_t Size>
void pack_float_array(Packer& packer, const std::array<float, Size>& values) {
  packer.pack_array(Size);
  for (const auto value : values) packer.pack(value);
}

template <typename Packer>
void pack_observation(Packer& packer, const LiveObservation& observation) {
  packer.pack_map(8);
  pack_field(packer, "timestamp_ns", observation.timestamp_ns);
  packer.pack(std::string("bbox"));
  pack_float_array(packer, observation.bbox);
  pack_field(packer, "detector_confidence", observation.detector_confidence);
  packer.pack(std::string("landmarks"));
  pack_float_array(packer, observation.landmarks);
  packer.pack(std::string("landmark_confidences"));
  pack_float_array(packer, observation.landmark_confidences);
  pack_field(packer, "quality_score", observation.quality.quality_score);
  pack_field(packer, "reject_mask", observation.quality.reject_mask);
  packer.pack(std::string("embedding"));
  pack_float_array(packer, observation.embedding);
}

template <typename Packer>
void pack_jpeg(Packer& packer, const std::vector<std::byte>& jpeg) {
  packer.pack_bin(static_cast<std::uint32_t>(jpeg.size()));
  packer.pack_bin_body(reinterpret_cast<const char*>(jpeg.data()),
                       static_cast<std::uint32_t>(jpeg.size()));
}

LiveMessage decode_payload(const ObjectMap& values) {
  const auto header = decode_header(values);
  if (header.message_type == "start") {
    validate_fields(values,
                    {"uri", "gpu_id", "pgie_config_path", "preprocess_config_path",
                      "sgie_config_path", "tracker_config_path", "output_mount_path",
                      "output_udp_port", "output_rtsp_port", "profile_version",
                      "analytics_mode", "sample_every_n", "detector_threshold",
                      "recognition_threshold", "top2_margin", "track_gap_ns",
                      "latency_ms", "reconnect_interval_seconds",
                      "reconnect_attempts", "frame_timeout_ns",
                      "recording_enabled", "annotated_enabled"});
    const auto port = unsigned_integer(required(values, "output_udp_port"), 1);
    const auto rtsp_port =
        unsigned_integer(required(values, "output_rtsp_port"), 1);
    const auto profile_version =
        unsigned_integer(required(values, "profile_version"), 1);
    const auto sample_every_n =
        unsigned_integer(required(values, "sample_every_n"), 1);
    const auto latency_ms = unsigned_integer(required(values, "latency_ms"));
    const auto reconnect_interval_seconds =
        unsigned_integer(required(values, "reconnect_interval_seconds"));
    if (port > std::numeric_limits<std::uint16_t>::max() ||
        rtsp_port > std::numeric_limits<std::uint16_t>::max() ||
        profile_version > std::numeric_limits<std::uint32_t>::max() ||
        sample_every_n > std::numeric_limits<std::uint32_t>::max() ||
        latency_ms > std::numeric_limits<std::uint32_t>::max() ||
        reconnect_interval_seconds > std::numeric_limits<std::uint32_t>::max()) {
      fail("INVALID_INTEGER");
    }
    const auto attempts = signed_integer(required(values, "reconnect_attempts"));
    if (attempts < -1 || attempts > std::numeric_limits<std::int32_t>::max()) {
      fail("INVALID_INTEGER");
    }
    const auto analytics_mode = string_value(required(values, "analytics_mode"));
    if (analytics_mode != "detect" && analytics_mode != "detectTrack" &&
        analytics_mode != "recognize") {
      fail("INVALID_PAYLOAD");
    }
    const auto detector_threshold =
        finite_number(required(values, "detector_threshold"));
    const auto recognition_threshold =
        finite_number(required(values, "recognition_threshold"));
    const auto top2_margin = finite_number(required(values, "top2_margin"));
    if (detector_threshold < 0.0 || detector_threshold > 1.0 ||
        recognition_threshold < 0.0 || recognition_threshold > 1.0 ||
        top2_margin < 0.0 || top2_margin > 1.0) {
      fail("INVALID_PAYLOAD");
    }
    const auto& recording_enabled = required(values, "recording_enabled");
    const auto& annotated_enabled = required(values, "annotated_enabled");
    if (recording_enabled.type != msgpack::type::BOOLEAN ||
        annotated_enabled.type != msgpack::type::BOOLEAN) {
      fail("INVALID_PAYLOAD");
    }
    return StartCommand{
        header,
        string_value(required(values, "uri")),
        static_cast<std::uint32_t>(unsigned_integer(required(values, "gpu_id"))),
        string_value(required(values, "pgie_config_path")),
        string_value(required(values, "preprocess_config_path")),
        string_value(required(values, "sgie_config_path")),
        string_value(required(values, "tracker_config_path")),
        string_value(required(values, "output_mount_path")),
        static_cast<std::uint16_t>(port),
        static_cast<std::uint16_t>(rtsp_port),
        static_cast<std::uint32_t>(profile_version),
        analytics_mode,
        static_cast<std::uint32_t>(sample_every_n),
        detector_threshold,
        recognition_threshold,
        top2_margin,
        unsigned_integer(required(values, "track_gap_ns"), 1),
        static_cast<std::uint32_t>(latency_ms),
        static_cast<std::uint32_t>(reconnect_interval_seconds),
        static_cast<std::int32_t>(attempts),
        unsigned_integer(required(values, "frame_timeout_ns"), 1),
        recording_enabled.as<bool>(),
        annotated_enabled.as<bool>()};
  }
  if (header.message_type == "identity_assignment") {
    validate_fields(values, {"tracker_id", "assignment_revision", "identity_epoch",
                             "identity_state", "display_name", "face_id",
                             "match_score", "recognition_threshold",
                             "reference_embedding",
                             "decision_sequence"});
    const auto state = string_value(required(values, "identity_state"));
    if (state != "known" && state != "unknown") fail("INVALID_PAYLOAD");
    auto display_name = optional_string(required(values, "display_name"));
    auto face_id = optional_string(required(values, "face_id"));
    if (face_id.has_value() && !canonical_uuid(*face_id)) fail("INVALID_UUID");
    auto match_score = optional_float(required(values, "match_score"));
    auto recognition_threshold =
        optional_float(required(values, "recognition_threshold"));
    std::optional<std::array<float, 512>> reference_embedding;
    const auto& reference = required(values, "reference_embedding");
    if (state == "known") {
      if (!display_name.has_value() || !face_id.has_value() ||
          !match_score.has_value() || !recognition_threshold.has_value() ||
          reference.is_nil()) {
        fail("INVALID_IDENTITY_ASSIGNMENT");
      }
      reference_embedding =
          float_array<512>(reference, "INVALID_EMBEDDING");
      double squared_norm = 0.0;
      for (const float value : *reference_embedding) squared_norm += value * value;
      const double norm = std::sqrt(squared_norm);
      if (norm < 0.99 || norm > 1.01) fail("INVALID_EMBEDDING_NORM");
    } else if (display_name.has_value() || face_id.has_value() ||
               match_score.has_value() || recognition_threshold.has_value() ||
               !reference.is_nil()) {
      fail("INVALID_IDENTITY_ASSIGNMENT");
    }
    return IdentityAssignment{
        header,
        unsigned_integer(required(values, "tracker_id")),
        unsigned_integer(required(values, "assignment_revision"), 1),
        unsigned_integer(required(values, "identity_epoch"), 1),
        state,
        std::move(display_name),
        std::move(face_id),
        match_score,
        recognition_threshold,
        std::move(reference_embedding),
        unsigned_integer(required(values, "decision_sequence"))};
  }
  if (header.message_type == "stop") {
    validate_fields(values, {"reason", "shutdown_deadline_ns"});
    return StopCommand{header, string_value(required(values, "reason")),
                       unsigned_integer(required(values, "shutdown_deadline_ns"), 1)};
  }
  if (header.message_type == "hello") {
    validate_fields(values, {"build_id", "gstreamer_version", "deepstream_version"});
    return HelloEvent{header, string_value(required(values, "build_id")),
                      string_value(required(values, "gstreamer_version")),
                      string_value(required(values, "deepstream_version"))};
  }
  if (header.message_type == "state") {
    validate_fields(values, {"state", "reason"});
    const auto state = string_value(required(values, "state"));
    static const std::set<std::string> states{
        "STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "STOPPED", "FAILED"};
    if (states.find(state) == states.end()) fail("INVALID_PAYLOAD");
    return StateEvent{header, state, optional_string(required(values, "reason"))};
  }
  if (header.message_type == "output_ready") {
    validate_fields(values, {"mount_path", "codec", "caps"});
    return OutputReadyEvent{header, string_value(required(values, "mount_path")),
                            string_value(required(values, "codec")),
                            string_value(required(values, "caps"))};
  }
  if (header.message_type == "track_evidence") {
    validate_fields(values, {"tracker_id", "evidence_revision", "first_seen_ns",
                             "last_seen_ns", "observations",
                             "representative_aligned_jpeg"});
    const auto& observation_values = required(values, "observations");
    if (observation_values.type != msgpack::type::ARRAY ||
        observation_values.via.array.size > kMaxLiveObservations) {
      fail("INVALID_PAYLOAD");
    }
    std::vector<LiveObservation> observations;
    observations.reserve(observation_values.via.array.size);
    for (std::uint32_t index = 0; index < observation_values.via.array.size; ++index) {
      observations.push_back(decode_observation(observation_values.via.array.ptr[index]));
    }
    const auto& jpeg_value = required(values, "representative_aligned_jpeg");
    if (jpeg_value.type != msgpack::type::BIN) fail("INVALID_PAYLOAD");
    if (jpeg_value.via.bin.size > kMaxAlignedJpegBytes) fail("SNAPSHOT_TOO_LARGE");
    std::vector<std::byte> jpeg(jpeg_value.via.bin.size);
    std::memcpy(jpeg.data(), jpeg_value.via.bin.ptr, jpeg_value.via.bin.size);
    return TrackEvidenceEvent{
        header,
        unsigned_integer(required(values, "tracker_id")),
        unsigned_integer(required(values, "evidence_revision"), 1),
        unsigned_integer(required(values, "first_seen_ns")),
        unsigned_integer(required(values, "last_seen_ns")),
        std::move(observations),
        std::move(jpeg)};
  }
  if (header.message_type == "track_expired") {
    validate_fields(values, {"tracker_id", "evidence_revision", "first_seen_ns",
                             "last_seen_ns", "reason"});
    return TrackExpiredEvent{
        header,
        unsigned_integer(required(values, "tracker_id")),
        unsigned_integer(required(values, "evidence_revision"), 1),
        unsigned_integer(required(values, "first_seen_ns")),
        unsigned_integer(required(values, "last_seen_ns")),
        string_value(required(values, "reason"))};
  }
  if (header.message_type == "metrics") {
    validate_fields(values, {"counters", "gauges"});
    const auto& counter_value = required(values, "counters");
    const auto& gauge_value = required(values, "gauges");
    if (counter_value.type != msgpack::type::MAP ||
        gauge_value.type != msgpack::type::MAP) {
      fail("INVALID_PAYLOAD");
    }
    std::map<std::string, std::uint64_t> counters;
    for (const auto& [key, value] : counter_value.as<ObjectMap>()) {
      counters.emplace(key, unsigned_integer(value));
    }
    std::map<std::string, double> gauges;
    for (const auto& [key, value] : gauge_value.as<ObjectMap>()) {
      gauges.emplace(key, finite_number(value));
    }
    return MetricsEvent{header, std::move(counters), std::move(gauges)};
  }
  if (header.message_type == "failed") {
    validate_fields(values, {"error_code", "message"});
    return FailedEvent{header, string_value(required(values, "error_code")),
                       string_value(required(values, "message"))};
  }
  if (header.message_type == "stopped") {
    validate_fields(values, {"decoded_frames", "emitted_evidence", "dropped_events",
                             "clean_shutdown", "reason"});
    const auto& clean = required(values, "clean_shutdown");
    if (clean.type != msgpack::type::BOOLEAN) fail("INVALID_PAYLOAD");
    return StoppedEvent{header,
                        unsigned_integer(required(values, "decoded_frames")),
                        unsigned_integer(required(values, "emitted_evidence")),
                        unsigned_integer(required(values, "dropped_events")),
                        clean.as<bool>(), string_value(required(values, "reason"))};
  }
  validate_fields(values, {"operation", "started_monotonic_ns",
                           "ended_monotonic_ns", "status", "error_code",
                           "attributes"});
  const auto operation = string_value(required(values, "operation"));
  const auto status = string_value(required(values, "status"));
  const auto error_code = optional_string(required(values, "error_code"));
  const auto started = unsigned_integer(required(values, "started_monotonic_ns"));
  const auto ended = unsigned_integer(required(values, "ended_monotonic_ns"));
  static const std::set<std::string> operations{
      "source_connect", "first_frame", "reconnect", "graph_rebuild",
      "inference_window", "output_start", "output_stop", "teardown"};
  static const std::set<std::string> attribute_keys{
      "attempt", "reason", "state", "outcome", "batch_size", "object_count"};
  static const std::regex stable_enum("^[a-z][a-z0-9_]{0,63}$");
  static const std::regex stable_error("^[A-Z][A-Z0-9_]{0,63}$");
  const auto& attribute_value = required(values, "attributes");
  if (operations.find(operation) == operations.end() ||
      (status != "ok" && status != "error") || ended < started ||
      (status == "error" && !error_code.has_value()) ||
      (status == "ok" && error_code.has_value()) ||
      (error_code.has_value() && !std::regex_match(*error_code, stable_error)) ||
      attribute_value.type != msgpack::type::MAP || attribute_value.via.map.size > 16) {
    fail("INVALID_NATIVE_OPERATION");
  }
  std::map<std::string, NativeAttribute> attributes;
  for (const auto& [key, value] : attribute_value.as<ObjectMap>()) {
    if (attribute_keys.find(key) == attribute_keys.end()) {
      fail("INVALID_NATIVE_OPERATION");
    }
    if (value.type == msgpack::type::STR) {
      const auto item = string_value(value);
      if (!std::regex_match(item, stable_enum)) fail("INVALID_NATIVE_OPERATION");
      attributes.emplace(key, item);
    } else if (value.type == msgpack::type::POSITIVE_INTEGER ||
               value.type == msgpack::type::NEGATIVE_INTEGER) {
      attributes.emplace(key, signed_integer(value));
    } else if (value.type == msgpack::type::FLOAT32 ||
               value.type == msgpack::type::FLOAT64) {
      attributes.emplace(key, finite_number(value));
    } else {
      fail("INVALID_NATIVE_OPERATION");
    }
  }
  return NativeOperationEvent{header, operation, started, ended, status,
                              error_code, std::move(attributes)};
}

}  // namespace

LiveProtocolError::LiveProtocolError(std::string code)
    : std::runtime_error(code), code_(std::move(code)) {}

const std::string& LiveProtocolError::code() const noexcept { return code_; }

std::vector<std::uint8_t> encode_live_message(const LiveMessage& message) {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  std::visit(
      [&](const auto& value) {
        using Message = std::decay_t<decltype(value)>;
        if constexpr (std::is_same_v<Message, StartCommand>) {
          packer.pack_map(32);
          pack_header(packer, value.header);
          pack_field(packer, "uri", value.uri);
          pack_field(packer, "gpu_id", value.gpu_id);
          pack_field(packer, "pgie_config_path", value.pgie_config_path);
          pack_field(packer, "preprocess_config_path", value.preprocess_config_path);
          pack_field(packer, "sgie_config_path", value.sgie_config_path);
          pack_field(packer, "tracker_config_path", value.tracker_config_path);
          pack_field(packer, "output_mount_path", value.output_mount_path);
          pack_field(packer, "output_udp_port", value.output_udp_port);
          pack_field(packer, "output_rtsp_port", value.output_rtsp_port);
          pack_field(packer, "profile_version", value.profile_version);
          pack_field(packer, "analytics_mode", value.analytics_mode);
          pack_field(packer, "sample_every_n", value.sample_every_n);
          pack_field(packer, "detector_threshold", value.detector_threshold);
          pack_field(packer, "recognition_threshold", value.recognition_threshold);
          pack_field(packer, "top2_margin", value.top2_margin);
          pack_field(packer, "track_gap_ns", value.track_gap_ns);
          pack_field(packer, "latency_ms", value.latency_ms);
          pack_field(packer, "reconnect_interval_seconds",
                     value.reconnect_interval_seconds);
          pack_field(packer, "reconnect_attempts", value.reconnect_attempts);
          pack_field(packer, "frame_timeout_ns", value.frame_timeout_ns);
          pack_field(packer, "recording_enabled", value.recording_enabled);
          pack_field(packer, "annotated_enabled", value.annotated_enabled);
        } else if constexpr (std::is_same_v<Message, IdentityAssignment>) {
          packer.pack_map(20);
          pack_header(packer, value.header);
          pack_field(packer, "tracker_id", value.tracker_id);
          pack_field(packer, "assignment_revision", value.assignment_revision);
          pack_field(packer, "identity_epoch", value.identity_epoch);
          pack_field(packer, "identity_state", value.identity_state);
          pack_optional(packer, "display_name", value.display_name);
          pack_optional(packer, "face_id", value.face_id);
          pack_optional(packer, "match_score", value.match_score);
          pack_optional(packer, "recognition_threshold",
                        value.recognition_threshold);
          pack_optional(packer, "reference_embedding", value.reference_embedding);
          pack_field(packer, "decision_sequence", value.decision_sequence);
        } else if constexpr (std::is_same_v<Message, StopCommand>) {
          packer.pack_map(12);
          pack_header(packer, value.header);
          pack_field(packer, "reason", value.reason);
          pack_field(packer, "shutdown_deadline_ns", value.shutdown_deadline_ns);
        } else if constexpr (std::is_same_v<Message, HelloEvent>) {
          packer.pack_map(13);
          pack_header(packer, value.header);
          pack_field(packer, "build_id", value.build_id);
          pack_field(packer, "gstreamer_version", value.gstreamer_version);
          pack_field(packer, "deepstream_version", value.deepstream_version);
        } else if constexpr (std::is_same_v<Message, StateEvent>) {
          packer.pack_map(12);
          pack_header(packer, value.header);
          pack_field(packer, "state", value.state);
          pack_optional(packer, "reason", value.reason);
        } else if constexpr (std::is_same_v<Message, OutputReadyEvent>) {
          packer.pack_map(13);
          pack_header(packer, value.header);
          pack_field(packer, "mount_path", value.mount_path);
          pack_field(packer, "codec", value.codec);
          pack_field(packer, "caps", value.caps);
        } else if constexpr (std::is_same_v<Message, TrackEvidenceEvent>) {
          packer.pack_map(16);
          pack_header(packer, value.header);
          pack_field(packer, "tracker_id", value.tracker_id);
          pack_field(packer, "evidence_revision", value.evidence_revision);
          pack_field(packer, "first_seen_ns", value.first_seen_ns);
          pack_field(packer, "last_seen_ns", value.last_seen_ns);
          packer.pack(std::string("observations"));
          packer.pack_array(value.observations.size());
          for (const auto& observation : value.observations) {
            pack_observation(packer, observation);
          }
          packer.pack(std::string("representative_aligned_jpeg"));
          pack_jpeg(packer, value.representative_aligned_jpeg);
        } else if constexpr (std::is_same_v<Message, TrackExpiredEvent>) {
          packer.pack_map(15);
          pack_header(packer, value.header);
          pack_field(packer, "tracker_id", value.tracker_id);
          pack_field(packer, "evidence_revision", value.evidence_revision);
          pack_field(packer, "first_seen_ns", value.first_seen_ns);
          pack_field(packer, "last_seen_ns", value.last_seen_ns);
          pack_field(packer, "reason", value.reason);
        } else if constexpr (std::is_same_v<Message, MetricsEvent>) {
          packer.pack_map(12);
          pack_header(packer, value.header);
          pack_field(packer, "counters", value.counters);
          pack_field(packer, "gauges", value.gauges);
        } else if constexpr (std::is_same_v<Message, FailedEvent>) {
          packer.pack_map(12);
          pack_header(packer, value.header);
          pack_field(packer, "error_code", value.error_code);
          pack_field(packer, "message", value.message);
        } else if constexpr (std::is_same_v<Message, StoppedEvent>) {
          packer.pack_map(15);
          pack_header(packer, value.header);
          pack_field(packer, "decoded_frames", value.decoded_frames);
          pack_field(packer, "emitted_evidence", value.emitted_evidence);
          pack_field(packer, "dropped_events", value.dropped_events);
          pack_field(packer, "clean_shutdown", value.clean_shutdown);
          pack_field(packer, "reason", value.reason);
        } else if constexpr (std::is_same_v<Message, NativeOperationEvent>) {
          packer.pack_map(16);
          pack_header(packer, value.header);
          pack_field(packer, "operation", value.operation);
          pack_field(packer, "started_monotonic_ns", value.started_monotonic_ns);
          pack_field(packer, "ended_monotonic_ns", value.ended_monotonic_ns);
          pack_field(packer, "status", value.status);
          pack_optional(packer, "error_code", value.error_code);
          packer.pack(std::string("attributes"));
          packer.pack_map(value.attributes.size());
          for (const auto& [key, attribute] : value.attributes) {
            packer.pack(key);
            std::visit([&packer](const auto& item) { packer.pack(item); }, attribute);
          }
        }
      },
      message);
  if (payload.size() > kMaxLiveFrameBytes) fail("FRAME_TOO_LARGE");
  const auto network_size = htonl(static_cast<std::uint32_t>(payload.size()));
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload.size());
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  std::memcpy(frame.data() + sizeof(network_size), payload.data(), payload.size());
  return frame;
}

LiveMessage decode_live_message(const std::vector<std::uint8_t>& frame,
                                DecodeContext* context) {
  if (frame.size() < sizeof(std::uint32_t)) fail("TRUNCATED_FRAME");
  std::uint32_t network_size = 0;
  std::memcpy(&network_size, frame.data(), sizeof(network_size));
  const auto payload_size = ntohl(network_size);
  if (payload_size > kMaxLiveFrameBytes) fail("FRAME_TOO_LARGE");
  if (frame.size() != sizeof(network_size) + payload_size) fail("TRUNCATED_FRAME");
  try {
    auto handle = msgpack::unpack(
        reinterpret_cast<const char*>(frame.data() + sizeof(network_size)), payload_size);
    if (handle.get().type != msgpack::type::MAP) fail("INVALID_PAYLOAD");
    auto message = decode_payload(handle.get().as<ObjectMap>());
    if (context != nullptr) {
      const auto header = std::visit(
          [](const auto& value) { return value.header; }, message);
      if (header.session_id != context->session_id) fail("WRONG_SESSION_ID");
      if (header.camera_id != context->camera_id) fail("WRONG_CAMERA_ID");
      if (header.run_id != context->run_id) fail("WRONG_RUN_ID");
      if (header.generation != context->generation) fail("WRONG_GENERATION");
      if (header.runtime_attempt != context->runtime_attempt) {
        fail("WRONG_RUNTIME_ATTEMPT");
      }
      if (auto* assignment = std::get_if<IdentityAssignment>(&message)) {
        const auto previous = context->assignment_revisions[assignment->tracker_id];
        if (assignment->assignment_revision <= previous) {
          fail("STALE_ASSIGNMENT_REVISION");
        }
        context->assignment_revisions[assignment->tracker_id] =
            assignment->assignment_revision;
      }
    }
    return message;
  } catch (const LiveProtocolError&) {
    throw;
  } catch (const std::exception&) {
    fail("INVALID_MESSAGEPACK");
  }
}

}  // namespace mvision
