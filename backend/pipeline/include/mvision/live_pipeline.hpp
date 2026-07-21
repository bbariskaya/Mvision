#pragma once

#include "mvision/live_protocol.hpp"

#include <cstdint>
#include <functional>
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
