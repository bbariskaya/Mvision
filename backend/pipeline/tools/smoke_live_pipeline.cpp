#include "mvision/live_pipeline.hpp"

#include <algorithm>
#include <chrono>
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
    bool inference_window = false;

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
    callbacks.on_native_operation = [&](const mvision::NativeOperationEvent& event) {
      std::lock_guard lock(mutex);
      source_connect = source_connect || event.operation == "source_connect";
      first_frame = first_frame || event.operation == "first_frame";
      inference_window = inference_window || event.operation == "inference_window";
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
        return counters.decoded_frames > 0 && counters.tracked_objects > 0 &&
               counters.embedding_count > 0 && source_connect && first_frame &&
               inference_window;
      });
    }
    pipeline.stop(mvision::StopReason::SmokeComplete);
    pipeline.close();

    const bool saw_starting = !states.empty() && states.front() == mvision::LiveRuntimeState::Starting;
    const bool saw_active = std::find(states.begin(), states.end(),
                                      mvision::LiveRuntimeState::Active) != states.end();
    const bool coverage = counters.embedding_count + counters.missing_embedding_count ==
                          counters.eligible_object_count;
    const bool pass = saw_starting && saw_active && counters.decoded_frames > 0 &&
                      counters.tracked_objects > 0 && counters.embedding_count > 0 &&
                      coverage && counters.invalid_embedding_count == 0 &&
                      source_connect && first_frame && inference_window;

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
              << ",\"sourceConnect\":" << (source_connect ? "true" : "false")
              << ",\"firstFrame\":" << (first_frame ? "true" : "false")
              << ",\"inferenceWindow\":" << (inference_window ? "true" : "false")
              << "}\n";
    return pass ? 0 : 1;
  } catch (const std::exception&) {
    std::cerr << "LIVE_SMOKE_FAILED\n";
    return 1;
  }
}
