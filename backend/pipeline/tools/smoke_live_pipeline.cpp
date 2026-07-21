#include "mvision/live_pipeline.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

int parse_int(const char* value, const char* code) {
  try {
    std::size_t consumed = 0;
    const int parsed = std::stoi(value, &consumed);
    if (consumed != std::string(value).size()) throw std::invalid_argument("suffix");
    return parsed;
  } catch (const std::exception&) {
    throw std::runtime_error(code);
  }
}

const char* state_name(mvision::LiveRuntimeState state) {
  switch (state) {
    case mvision::LiveRuntimeState::Starting:
      return "STARTING";
    case mvision::LiveRuntimeState::Active:
      return "ACTIVE";
    case mvision::LiveRuntimeState::Reconnecting:
      return "RECONNECTING";
    case mvision::LiveRuntimeState::Stopping:
      return "STOPPING";
    case mvision::LiveRuntimeState::Stopped:
      return "STOPPED";
    case mvision::LiveRuntimeState::Failed:
      return "FAILED";
  }
  return "FAILED";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 7) {
    std::cerr << "LIVE_SMOKE_USAGE_ERROR\n";
    return 2;
  }
  std::string uri;
  if (!std::getline(std::cin, uri) || uri.empty()) {
    std::cerr << "LIVE_SMOKE_URI_REQUIRED\n";
    return 2;
  }

  try {
    std::mutex mutex;
    std::condition_variable changed;
    std::vector<mvision::LiveRuntimeState> states;
    mvision::LivePipelineCounters counters{};
    bool source_connect = false;
    bool first_frame = false;
    std::uint64_t inference_windows = 0;
    bool evidence_valid = true;
    std::uint64_t evidence_count = 0;

    mvision::LivePipelineCallbacks callbacks;
    callbacks.on_state = [&](mvision::LiveRuntimeState state) {
      std::lock_guard lock(mutex);
      states.push_back(state);
      changed.notify_all();
    };
    callbacks.on_metrics = [&](const mvision::LivePipelineCounters& value) {
      std::lock_guard lock(mutex);
      counters = value;
      changed.notify_all();
    };
    callbacks.on_evidence = [&](const mvision::TrackEvidenceEvent& event) {
      std::lock_guard lock(mutex);
      for (const auto& observation : event.observations) {
        double norm_squared = 0.0;
        for (const float value : observation.embedding) {
          evidence_valid = evidence_valid && std::isfinite(value);
          norm_squared += static_cast<double>(value) * value;
        }
        const double norm = std::sqrt(norm_squared);
        evidence_valid = evidence_valid && norm >= 0.99 && norm <= 1.01 &&
                         observation.frame_width > 0 && observation.frame_height > 0 &&
                         observation.bbox[0] >= 0.0F && observation.bbox[1] >= 0.0F &&
                         observation.bbox[0] + observation.bbox[2] <=
                             static_cast<float>(observation.frame_width) &&
                         observation.bbox[1] + observation.bbox[3] <=
                             static_cast<float>(observation.frame_height);
        for (std::size_t index = 0; index < observation.landmarks.size(); index += 2) {
          evidence_valid = evidence_valid && observation.landmarks[index] >= 0.0F &&
                           observation.landmarks[index] <= observation.frame_width &&
                           observation.landmarks[index + 1] >= 0.0F &&
                           observation.landmarks[index + 1] <= observation.frame_height;
        }
        ++evidence_count;
      }
      changed.notify_all();
    };
    callbacks.on_native_operation = [&](const mvision::NativeOperationEvent& event) {
      std::lock_guard lock(mutex);
      source_connect = source_connect || event.operation == "source_connect";
      first_frame = first_frame || event.operation == "first_frame";
      if (event.operation == "inference_window") ++inference_windows;
      changed.notify_all();
    };

    mvision::LivePipelineOptions options;
    options.uri = std::move(uri);
    options.gpu_id = parse_int(argv[1], "LIVE_SMOKE_INVALID_GPU");
    options.pgie_config_path = argv[2];
    options.tracker_config_path = argv[3];
    options.preprocess_config_path = argv[4];
    options.sgie_config_path = argv[5];
    options.batch_size = 1;
    options.live_source = true;

    mvision::LivePipeline pipeline(std::move(callbacks));
    pipeline.start(options);
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::seconds(parse_int(argv[6], "LIVE_SMOKE_INVALID_DEADLINE"));
    {
      std::unique_lock lock(mutex);
      changed.wait_until(lock, deadline, [&] {
        return counters.decoded_frames >= 120 && counters.tracked_objects > 0 &&
               counters.embedding_count > 0 && evidence_count > 0 && evidence_valid &&
               source_connect && first_frame && inference_windows > 0;
      });
    }
    pipeline.stop(mvision::StopReason::SmokeComplete);
    pipeline.close();

    const bool saw_starting = !states.empty() && states.front() == mvision::LiveRuntimeState::Starting;
    const bool saw_active = std::find(states.begin(), states.end(),
                                      mvision::LiveRuntimeState::Active) != states.end();
    const bool coverage = counters.embedding_count + counters.missing_embedding_count ==
                          counters.eligible_object_count;
    const double embedding_norm_mean = counters.embedding_norm_samples == 0
                                           ? 0.0
                                           : counters.embedding_norm_sum /
                                                 counters.embedding_norm_samples;
    const double embedding_cosine_mean = counters.embedding_cosine_samples == 0
                                             ? 0.0
                                             : counters.embedding_cosine_sum /
                                                   counters.embedding_cosine_samples;
    const bool pass = saw_starting && saw_active && counters.decoded_frames >= 120 &&
                       counters.tracked_objects > 0 && counters.embedding_count > 0 &&
                       coverage && counters.invalid_embedding_count == 0 &&
                       counters.pipeline_errors == 0 &&
                       evidence_count > 0 && evidence_valid && source_connect &&
                       first_frame && inference_windows > 0 && inference_windows <= 2;

    std::cout << "{\"states\":[";
    for (std::size_t index = 0; index < states.size(); ++index) {
      if (index != 0) std::cout << ',';
      std::cout << '\"' << state_name(states[index]) << '\"';
    }
    std::cout << "],\"decodedFrames\":" << counters.decoded_frames
              << ",\"trackedObjects\":" << counters.tracked_objects
              << ",\"eligibleObjects\":" << counters.eligible_object_count
              << ",\"embeddingCount\":" << counters.embedding_count
              << ",\"missingEmbeddingCount\":" << counters.missing_embedding_count
               << ",\"invalidEmbeddingCount\":" << counters.invalid_embedding_count
               << ",\"embeddingNormMin\":" << counters.embedding_norm_min
               << ",\"embeddingNormMax\":" << counters.embedding_norm_max
               << ",\"embeddingNormMean\":" << embedding_norm_mean
               << ",\"embeddingCosineMean\":" << embedding_cosine_mean
               << ",\"embeddingCosineSamples\":" << counters.embedding_cosine_samples
               << ",\"trackerIdSwitches\":" << counters.tracker_id_switches
               << ",\"pipelineWarnings\":" << counters.pipeline_warnings
               << ",\"pipelineErrors\":" << counters.pipeline_errors
               << ",\"evidenceCount\":" << evidence_count
               << ",\"evidenceValid\":" << (evidence_valid ? "true" : "false")
              << ",\"sourceConnect\":" << (source_connect ? "true" : "false")
              << ",\"firstFrame\":" << (first_frame ? "true" : "false")
               << ",\"inferenceWindows\":" << inference_windows
              << "}\n";
    return pass ? 0 : 1;
  } catch (const std::exception&) {
    std::cerr << "LIVE_SMOKE_FAILED\n";
    return 1;
  }
}
