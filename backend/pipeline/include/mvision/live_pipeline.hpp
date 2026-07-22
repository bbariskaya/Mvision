#pragma once

#include "mvision/live_protocol.hpp"

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

namespace mvision {

enum class LiveRuntimeState {
  Starting,
  Active,
  Reconnecting,
  Stopping,
  Stopped,
  Failed,
};

enum class StopReason {
  SmokeComplete,
  Requested,
  Failure,
};

enum class LifecycleAction {
  None,
  RebuildGraph,
};

struct LiveLifecycleOptions {
  std::uint64_t frame_timeout_ns{};
  std::uint64_t recovery_deadline_ns{};
  std::uint32_t graph_rebuild_attempts{};
};

class LiveLifecycle {
 public:
  using Clock = std::function<std::uint64_t()>;
  using StateSink = std::function<void(LiveRuntimeState)>;
  using FailureSink = std::function<void(std::string, std::string)>;

  LiveLifecycle(LiveLifecycleOptions options, Clock clock,
                StateSink state_sink, FailureSink failure_sink);

  void start();
  void on_frame();
  LifecycleAction poll();
  void on_graph_rebuild_result(bool success);
  void stop();
  void close();
  LiveRuntimeState state() const;

 private:
  void transition(LiveRuntimeState next);
  void invalid_transition();
  void fail(std::string code, std::string message);

  LiveLifecycleOptions options_;
  Clock clock_;
  StateSink state_sink_;
  FailureSink failure_sink_;
  mutable std::mutex mutex_;
  LiveRuntimeState state_{LiveRuntimeState::Stopped};
  std::uint64_t last_frame_ns_{};
  std::uint64_t reconnect_started_ns_{};
  std::uint32_t rebuild_attempts_{};
  bool started_{};
  bool awaiting_rebuild_result_{};
  bool failure_emitted_{};
};

struct LivePipelineCounters {
  std::uint64_t decoded_frames{};
  std::uint64_t tracked_objects{};
  std::uint64_t eligible_object_count{};
  std::uint64_t embedding_count{};
  std::uint64_t missing_embedding_count{};
  std::uint64_t invalid_embedding_count{};
  std::uint64_t emitted_evidence{};
  double embedding_norm_min{};
  double embedding_norm_max{};
  double embedding_norm_sum{};
  std::uint64_t embedding_norm_samples{};
  double embedding_cosine_sum{};
  std::uint64_t embedding_cosine_samples{};
  std::uint64_t tracker_id_switches{};
  std::uint64_t pipeline_warnings{};
  std::uint64_t pipeline_errors{};
  std::uint64_t output_buffers{};
  std::uint64_t dropped_output_buffers{};
};

struct LivePipelineOptions {
  std::string uri;
  int gpu_id{};
  std::string pgie_config_path;
  std::string tracker_config_path;
  std::string preprocess_config_path;
  std::string sgie_config_path;
  std::uint32_t batch_size{1};
  bool live_source{true};
  std::uint32_t width{1920};
  std::uint32_t height{1080};
  std::uint32_t sample_every_n{1};
  std::uint32_t latency_ms{200};
  std::uint32_t reconnect_interval_seconds{2};
  std::int32_t reconnect_attempts{-1};
  std::uint64_t frame_timeout_ns{2'000'000'000};
  std::uint64_t recovery_deadline_ns{5'000'000'000};
  std::uint32_t graph_rebuild_attempts{3};
  std::uint32_t initial_rebuild_backoff_ms{250};
  std::uint32_t max_rebuild_backoff_ms{2'000};
  std::string output_mount_path;
  std::uint16_t output_udp_port{5400};
  std::uint16_t output_rtsp_port{8554};
  ProtocolHeader event_header{};
};

struct LivePipelineCallbacks {
  std::function<void(LiveRuntimeState)> on_state;
  std::function<void(const OutputReadyEvent&)> on_output;
  std::function<void(const TrackEvidenceEvent&)> on_evidence;
  std::function<void(const LivePipelineCounters&)> on_metrics;
  std::function<void(const NativeOperationEvent&)> on_native_operation;
  std::function<void(const FailedEvent&)> on_failure;
  std::function<void(const StoppedEvent&)> on_stopped;
};

class LivePipeline {
 public:
  explicit LivePipeline(LivePipelineCallbacks callbacks);
  ~LivePipeline();

  LivePipeline(const LivePipeline&) = delete;
  LivePipeline& operator=(const LivePipeline&) = delete;

  void start(const LivePipelineOptions& options);
  bool apply_assignment(const IdentityAssignment& assignment);
  void stop(StopReason reason);
  void close();

 private:
  class Impl;
  Impl* impl_;
};

}  // namespace mvision
