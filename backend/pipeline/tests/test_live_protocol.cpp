#include "mvision/live_protocol.hpp"

#include <arpa/inet.h>
#include <msgpack.hpp>

#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                        \
  do {                                                                           \
    if (!(condition)) throw std::runtime_error("assertion failed: " #condition); \
  } while (false)
#endif

namespace {

constexpr const char* kCameraId = "019b0000-0000-7000-8000-000000000001";
constexpr const char* kRunId = "019b0000-0000-7000-8000-000000000002";
constexpr const char* kFaceId = "019b0000-0000-7000-8000-000000000003";
constexpr const char* kTraceparent =
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
constexpr const char* kTracestate = "vendor=value";

mvision::ProtocolHeader header(std::string type, std::uint64_t sequence = 7) {
  return {1, std::move(type), kCameraId, kRunId, 1, sequence, kTraceparent,
          std::string(kTracestate)};
}

mvision::LiveObservation observation() {
  mvision::LiveObservation value;
  value.timestamp_ns = 1'000'000'000;
  value.bbox = {10.0F, 20.0F, 100.0F, 120.0F};
  value.detector_confidence = 0.91F;
  value.landmarks = {1.0F, 2.0F, 3.0F, 4.0F, 5.0F,
                     6.0F, 7.0F, 8.0F, 9.0F, 10.0F};
  value.landmark_confidences = {0.9F, 0.8F, 0.7F, 0.6F, 0.5F};
  value.quality.quality_score = 0.72F;
  value.embedding.fill(0.0F);
  value.embedding[0] = 1.0F;
  return value;
}

mvision::StartCommand start_command() {
  return {header("start"),
          "rtsp://camera.invalid/live",
          0,
          "pgie.txt",
          "preprocess.txt",
          "sgie.txt",
          "tracker.yml",
          "/live/camera",
          5400,
          200,
          10,
          -1,
          5'000'000'000};
}

void expect_error(const std::string& code, const std::vector<std::uint8_t>& frame,
                  mvision::DecodeContext* context = nullptr) {
  try {
    static_cast<void>(mvision::decode_live_message(frame, context));
    throw std::runtime_error("expected protocol error");
  } catch (const mvision::LiveProtocolError& error) {
    if (error.code() != code) {
      std::cerr << "expected " << code << " but received " << error.code() << '\n';
    }
    assert(error.code() == code);
  }
}

std::vector<std::uint8_t> frame_map(
    const std::map<std::string, msgpack::object>& values,
    msgpack::zone& zone) {
  msgpack::sbuffer payload;
  msgpack::pack(payload, values);
  const auto size = static_cast<std::uint32_t>(payload.size());
  const auto network_size = htonl(size);
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload.size());
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  std::memcpy(frame.data() + sizeof(network_size), payload.data(), payload.size());
  static_cast<void>(zone);
  return frame;
}

std::vector<std::uint8_t> frame_buffer(const msgpack::sbuffer& payload) {
  const auto size = static_cast<std::uint32_t>(payload.size());
  const auto network_size = htonl(size);
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload.size());
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  std::memcpy(frame.data() + sizeof(network_size), payload.data(), payload.size());
  return frame;
}

void pack_raw_header(msgpack::packer<msgpack::sbuffer>& packer,
                     const std::string& type) {
  packer.pack(std::string("protocol_version"));
  packer.pack(1);
  packer.pack(std::string("message_type"));
  packer.pack(type);
  packer.pack(std::string("camera_id"));
  packer.pack(std::string(kCameraId));
  packer.pack(std::string("run_id"));
  packer.pack(std::string(kRunId));
  packer.pack(std::string("generation"));
  packer.pack(1);
  packer.pack(std::string("sequence"));
  packer.pack(7);
  packer.pack(std::string("traceparent"));
  packer.pack(std::string(kTraceparent));
  packer.pack(std::string("tracestate"));
  packer.pack(std::string(kTracestate));
}

std::vector<std::uint8_t> malformed_evidence(std::size_t embedding_size,
                                             std::size_t landmark_size) {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  packer.pack_map(14);
  pack_raw_header(packer, "track_evidence");
  packer.pack(std::string("tracker_id"));
  packer.pack(42);
  packer.pack(std::string("evidence_revision"));
  packer.pack(1);
  packer.pack(std::string("first_seen_ns"));
  packer.pack(1);
  packer.pack(std::string("last_seen_ns"));
  packer.pack(2);
  packer.pack(std::string("observations"));
  packer.pack_array(1);
  packer.pack_map(8);
  packer.pack(std::string("timestamp_ns"));
  packer.pack(1);
  packer.pack(std::string("bbox"));
  packer.pack(std::array<float, 4>{0.0F, 0.0F, 10.0F, 10.0F});
  packer.pack(std::string("detector_confidence"));
  packer.pack(0.9F);
  packer.pack(std::string("landmarks"));
  packer.pack_array(landmark_size);
  for (std::size_t index = 0; index < landmark_size; ++index) packer.pack(1.0F);
  packer.pack(std::string("landmark_confidences"));
  packer.pack(std::array<float, 5>{1.0F, 1.0F, 1.0F, 1.0F, 1.0F});
  packer.pack(std::string("quality_score"));
  packer.pack(0.8F);
  packer.pack(std::string("reject_mask"));
  packer.pack(0);
  packer.pack(std::string("embedding"));
  packer.pack_array(embedding_size);
  for (std::size_t index = 0; index < embedding_size; ++index) {
    packer.pack(index == 0 ? 1.0F : 0.0F);
  }
  packer.pack(std::string("representative_aligned_jpeg"));
  packer.pack_bin(0);
  return frame_buffer(payload);
}

std::vector<std::uint8_t> non_finite_metrics() {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  packer.pack_map(10);
  pack_raw_header(packer, "metrics");
  packer.pack(std::string("counters"));
  packer.pack_map(0);
  packer.pack(std::string("gauges"));
  packer.pack_map(1);
  packer.pack(std::string("fps"));
  packer.pack(std::numeric_limits<double>::quiet_NaN());
  return frame_buffer(payload);
}

void run_unit_tests() {
  const auto start = start_command();
  const auto decoded = std::get<mvision::StartCommand>(
      mvision::decode_live_message(mvision::encode_live_message(start)));
  assert(decoded.header.protocol_version == start.header.protocol_version);
  assert(decoded.header.message_type == start.header.message_type);
  assert(decoded.header.camera_id == start.header.camera_id);
  assert(decoded.header.run_id == start.header.run_id);
  assert(decoded.header.generation == start.header.generation);
  assert(decoded.header.sequence == start.header.sequence);
  assert(decoded.header.traceparent == start.header.traceparent);
  assert(decoded.header.tracestate == start.header.tracestate);
  assert(decoded.uri == start.uri);
  assert(decoded.gpu_id == start.gpu_id);
  assert(decoded.pgie_config_path == start.pgie_config_path);
  assert(decoded.preprocess_config_path == start.preprocess_config_path);
  assert(decoded.sgie_config_path == start.sgie_config_path);
  assert(decoded.tracker_config_path == start.tracker_config_path);
  assert(decoded.output_mount_path == start.output_mount_path);
  assert(decoded.output_udp_port == start.output_udp_port);
  assert(decoded.latency_ms == start.latency_ms);
  assert(decoded.reconnect_interval_seconds == start.reconnect_interval_seconds);
  assert(decoded.reconnect_attempts == start.reconnect_attempts);
  assert(decoded.frame_timeout_ns == start.frame_timeout_ns);

  expect_error("TRUNCATED_FRAME", {});
  expect_error("TRUNCATED_FRAME", {0, 0, 0});
  expect_error("TRUNCATED_FRAME", {0, 0, 0, 8, 1, 2, 3});
  const auto oversized = htonl(mvision::kMaxLiveFrameBytes + 1U);
  std::vector<std::uint8_t> oversized_frame(sizeof(oversized));
  std::memcpy(oversized_frame.data(), &oversized, sizeof(oversized));
  expect_error("FRAME_TOO_LARGE", oversized_frame);

  msgpack::zone zone;
  std::map<std::string, msgpack::object> invalid_header{
      {"protocol_version", msgpack::object(2, zone)},
      {"message_type", msgpack::object(std::string("state"), zone)},
      {"camera_id", msgpack::object(std::string(kCameraId), zone)},
      {"run_id", msgpack::object(std::string(kRunId), zone)},
      {"generation", msgpack::object(1, zone)},
      {"sequence", msgpack::object(7, zone)},
      {"traceparent", msgpack::object(std::string(kTraceparent), zone)},
      {"tracestate", msgpack::object(std::string(kTracestate), zone)},
      {"state", msgpack::object(std::string("ACTIVE"), zone)},
      {"reason", msgpack::object(msgpack::type::nil_t(), zone)},
  };
  expect_error("UNSUPPORTED_PROTOCOL_VERSION", frame_map(invalid_header, zone));
  invalid_header["protocol_version"] = msgpack::object(1, zone);
  invalid_header["message_type"] = msgpack::object(std::string("future"), zone);
  expect_error("UNKNOWN_MESSAGE_TYPE", frame_map(invalid_header, zone));
  invalid_header["message_type"] = msgpack::object(std::string("state"), zone);
  invalid_header["camera_id"] = msgpack::object(std::string("bad"), zone);
  expect_error("INVALID_UUID", frame_map(invalid_header, zone));
  invalid_header["camera_id"] = msgpack::object(std::string(kCameraId), zone);
  invalid_header["traceparent"] = msgpack::object(
      std::string("00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01"), zone);
  expect_error("INVALID_TRACE_CONTEXT", frame_map(invalid_header, zone));
  invalid_header["traceparent"] = msgpack::object(std::string(kTraceparent), zone);
  invalid_header["tracestate"] = msgpack::object(std::string(513, 'x'), zone);
  expect_error("INVALID_TRACE_CONTEXT", frame_map(invalid_header, zone));
  invalid_header["tracestate"] = msgpack::object(std::string(kTracestate), zone);
  invalid_header.erase("state");
  expect_error("MISSING_FIELD", frame_map(invalid_header, zone));
  invalid_header["state"] = msgpack::object(std::string("ACTIVE"), zone);
  invalid_header["future"] = msgpack::object(1, zone);
  expect_error("UNKNOWN_FIELD", frame_map(invalid_header, zone));

  expect_error("INVALID_EMBEDDING", malformed_evidence(511, 10));
  expect_error("INVALID_LANDMARKS", malformed_evidence(512, 9));
  expect_error("NON_FINITE_VALUE", non_finite_metrics());

  mvision::TrackEvidenceEvent evidence{
      header("track_evidence"), 42, 2, 1'000'000'000, 2'000'000'000,
      {observation()},
      {std::byte{0xFF}, std::byte{0xD8}, std::byte{0xFF}, std::byte{0xD9}}};
  auto invalid_embedding = evidence;
  invalid_embedding.observations[0].embedding.fill(0.0F);
  expect_error("INVALID_EMBEDDING_NORM",
               mvision::encode_live_message(invalid_embedding));
  invalid_embedding.observations[0].embedding[0] =
      std::numeric_limits<float>::infinity();
  expect_error("NON_FINITE_VALUE", mvision::encode_live_message(invalid_embedding));

  auto oversized_snapshot = evidence;
  oversized_snapshot.representative_aligned_jpeg.resize(
      mvision::kMaxAlignedJpegBytes + 1U);
  expect_error("SNAPSHOT_TOO_LARGE",
               mvision::encode_live_message(oversized_snapshot));

  mvision::DecodeContext wrong_generation{kCameraId, kRunId, 2, {}};
  expect_error("WRONG_GENERATION",
               mvision::encode_live_message(mvision::StateEvent{
                   header("state"), "ACTIVE", std::nullopt}),
               &wrong_generation);

  mvision::IdentityAssignment assignment{
      header("identity_assignment"), 42, 3, "known", std::string("Ada"),
      std::string(kFaceId), 0.87F, 12};
  mvision::DecodeContext revision_context{kCameraId, kRunId, 1, {}};
  static_cast<void>(mvision::decode_live_message(
      mvision::encode_live_message(assignment), &revision_context));
  expect_error("STALE_ASSIGNMENT_REVISION",
               mvision::encode_live_message(assignment), &revision_context);

  mvision::NativeOperationEvent operation{
      header("native_operation"), "reconnect", 1'000'000'000, 1'200'000'000,
      "ok", std::nullopt,
      {{"attempt", std::int64_t{2}}, {"outcome", std::string("recovered")}}};
  const auto decoded_operation = std::get<mvision::NativeOperationEvent>(
      mvision::decode_live_message(mvision::encode_live_message(operation)));
  assert(decoded_operation.operation == "reconnect");
  assert(decoded_operation.started_monotonic_ns == 1'000'000'000);
  assert(decoded_operation.ended_monotonic_ns == 1'200'000'000);
  assert(decoded_operation.attributes == operation.attributes);
}

void write_frame(const mvision::LiveMessage& message) {
  const auto frame = mvision::encode_live_message(message);
  std::cout.write(reinterpret_cast<const char*>(frame.data()),
                  static_cast<std::streamsize>(frame.size()));
}

void run_parity() {
  const std::vector<std::uint8_t> input(
      std::istreambuf_iterator<char>(std::cin), std::istreambuf_iterator<char>());
  std::size_t offset = 0;
  std::vector<mvision::LiveMessage> commands;
  while (offset < input.size()) {
    assert(input.size() - offset >= sizeof(std::uint32_t));
    std::uint32_t network_size = 0;
    std::memcpy(&network_size, input.data() + offset, sizeof(network_size));
    const auto payload_size = ntohl(network_size);
    const auto frame_size = sizeof(network_size) + payload_size;
    assert(offset + frame_size <= input.size());
    commands.push_back(mvision::decode_live_message(std::vector<std::uint8_t>(
        input.begin() + static_cast<std::ptrdiff_t>(offset),
        input.begin() + static_cast<std::ptrdiff_t>(offset + frame_size))));
    offset += frame_size;
  }
  assert(commands.size() == 3);
  const auto& start = std::get<mvision::StartCommand>(commands[0]);
  const auto& assignment = std::get<mvision::IdentityAssignment>(commands[1]);
  const auto& stop = std::get<mvision::StopCommand>(commands[2]);
  assert(start.header.sequence == 1);
  assert(start.uri == "rtsp://camera.invalid/live");
  assert(start.gpu_id == 0);
  assert(start.pgie_config_path == "pgie.txt");
  assert(start.preprocess_config_path == "preprocess.txt");
  assert(start.sgie_config_path == "sgie.txt");
  assert(start.tracker_config_path == "tracker.yml");
  assert(start.output_mount_path == "/live/camera");
  assert(start.output_udp_port == 5400);
  assert(start.latency_ms == 200);
  assert(start.reconnect_interval_seconds == 10);
  assert(start.reconnect_attempts == -1);
  assert(start.frame_timeout_ns == 5'000'000'000);
  assert(assignment.header.sequence == 2);
  assert(assignment.tracker_id == 42);
  assert(assignment.assignment_revision == 3);
  assert(assignment.identity_state == "known");
  assert(assignment.display_name == std::optional<std::string>("Ada"));
  assert(assignment.face_id == std::optional<std::string>(kFaceId));
  assert(assignment.match_score.has_value());
  assert(std::fabs(*assignment.match_score - 0.87F) < 1e-6F);
  assert(assignment.decision_sequence == 12);
  assert(stop.header.sequence == 3);
  assert(stop.reason == "operator");
  assert(stop.shutdown_deadline_ns == 2'000'000'000);

  write_frame(mvision::HelloEvent{header("hello", 101), "parity-build", "1.24.2",
                                  "9.0.0"});
  write_frame(mvision::TrackEvidenceEvent{
      header("track_evidence", 102), assignment.tracker_id,
      assignment.assignment_revision, 1'000'000'000, 2'000'000'000,
      {observation()},
      {std::byte{0xFF}, std::byte{0xD8}, std::byte{0xFF}, std::byte{0xD9}}});
  write_frame(mvision::NativeOperationEvent{
      header("native_operation", 103), "first_frame", 1'000'000'000,
      1'100'000'000, "ok", std::nullopt,
      {{"object_count", std::int64_t{1}}, {"outcome", std::string("active")}}});
  write_frame(mvision::StoppedEvent{header("stopped", 104), 20, 1, 0, true,
                                    stop.reason});
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--parity") {
    run_parity();
    return 0;
  }
  run_unit_tests();
  return 0;
}
