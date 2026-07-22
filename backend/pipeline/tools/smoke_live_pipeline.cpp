#include "mvision/live_pipeline.hpp"

#include <cuda_runtime_api.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
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

std::uint64_t entry_count(const char* path) {
  return static_cast<std::uint64_t>(
      std::distance(std::filesystem::directory_iterator(path),
                    std::filesystem::directory_iterator{}));
}

std::uint64_t settled_entry_count(const char* path) {
  std::uint64_t previous = entry_count(path);
  std::uint32_t stable_samples = 0;
  for (std::uint32_t sample = 0; sample < 40; ++sample) {
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    const std::uint64_t current = entry_count(path);
    if (current == previous) {
      if (++stable_samples == 10) return current;
    } else {
      previous = current;
      stable_samples = 0;
    }
  }
  return previous;
}

std::uint64_t used_gpu_bytes() {
  std::size_t free_bytes = 0;
  std::size_t total_bytes = 0;
  if (cudaMemGetInfo(&free_bytes, &total_bytes) != cudaSuccess) {
    throw std::runtime_error("LIVE_SMOKE_CUDA_MEMORY_ERROR");
  }
  return static_cast<std::uint64_t>(total_bytes - free_bytes);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 7 || argc > 10) {
    std::cerr << "LIVE_SMOKE_USAGE_ERROR\n";
    return 2;
  }
  std::string uri;
  if (!std::getline(std::cin, uri) || uri.empty()) {
    std::cerr << "LIVE_SMOKE_URI_REQUIRED\n";
    return 2;
  }

  try {
    const int cycle_count =
        argc == 10 ? parse_int(argv[9], "LIVE_SMOKE_INVALID_CYCLE_COUNT") : 1;
    if (cycle_count <= 0) throw std::runtime_error("LIVE_SMOKE_INVALID_CYCLE_COUNT");
    std::uint64_t baseline_fds = 0;
    std::uint64_t baseline_threads = 0;
    std::uint64_t baseline_gpu_bytes = 0;
    for (int cycle = 0; cycle < cycle_count; ++cycle) {
    std::mutex mutex;
    std::condition_variable changed;
    std::vector<mvision::LiveRuntimeState> states;
    mvision::LivePipelineCounters counters{};
    bool source_connect = false;
    bool first_frame = false;
    bool output_ready = false;
    std::uint64_t inference_windows = 0;
    std::uint64_t reconnect_operations = 0;
    std::uint64_t graph_rebuild_operations = 0;
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
    callbacks.on_output = [&](const mvision::OutputReadyEvent&) {
      std::lock_guard lock(mutex);
      output_ready = true;
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
      if (event.operation == "reconnect") ++reconnect_operations;
      if (event.operation == "graph_rebuild") ++graph_rebuild_operations;
      changed.notify_all();
    };

    mvision::LivePipelineOptions options;
    options.uri = uri;
    options.gpu_id = parse_int(argv[1], "LIVE_SMOKE_INVALID_GPU");
    options.pgie_config_path = argv[2];
    options.tracker_config_path = argv[3];
    options.preprocess_config_path = argv[4];
    options.sgie_config_path = argv[5];
    options.batch_size = 1;
    options.live_source = true;
    options.output_mount_path =
        "/live/019b0000-0000-7000-8000-000000000001";
    options.event_header = {
        1,
        "start",
        "019b0000-0000-7000-8000-000000000001",
        "019b0000-0000-7000-8000-000000000002",
        1,
        1,
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        std::nullopt};
    if (argc == 9) {
      options.initial_rebuild_backoff_ms = static_cast<std::uint32_t>(
          parse_int(argv[8], "LIVE_SMOKE_INVALID_REBUILD_BACKOFF"));
      options.max_rebuild_backoff_ms = options.initial_rebuild_backoff_ms;
    }

    mvision::LivePipeline pipeline(std::move(callbacks));
    pipeline.start(options);
    const auto deadline = std::chrono::steady_clock::now() +
                           std::chrono::seconds(parse_int(argv[6], "LIVE_SMOKE_INVALID_DEADLINE"));
    const std::uint64_t minimum_frames =
        argc >= 8 ? static_cast<std::uint64_t>(
                        parse_int(argv[7], "LIVE_SMOKE_INVALID_MINIMUM_FRAMES"))
                  : 120;
    {
      std::unique_lock lock(mutex);
      changed.wait_until(lock, deadline, [&] {
        return counters.decoded_frames >= minimum_frames && counters.tracked_objects > 0 &&
               counters.embedding_count > 1 &&
               counters.embedding_cosine_samples > 1 && evidence_count > 0 &&
               evidence_valid &&
               source_connect && first_frame && output_ready &&
               counters.output_buffers > 0 && inference_windows > 0;
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
    const std::uint64_t maximum_inference_windows = minimum_frames / 120 + 1;
    const bool pass = saw_starting && saw_active &&
                       counters.decoded_frames >= minimum_frames &&
                        counters.tracked_objects > 0 && counters.embedding_count > 1 &&
                        counters.embedding_cosine_samples > 1 &&
                       coverage && counters.invalid_embedding_count == 0 &&
                       counters.pipeline_errors == 0 &&
                        evidence_count > 0 && evidence_valid && source_connect &&
                        first_frame && output_ready && counters.output_buffers > 0 &&
                        inference_windows > 0 &&
                       inference_windows <= maximum_inference_windows;

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
               << ",\"outputBuffers\":" << counters.output_buffers
               << ",\"droppedOutputBuffers\":"
               << counters.dropped_output_buffers
               << ",\"evidenceCount\":" << evidence_count
               << ",\"evidenceValid\":" << (evidence_valid ? "true" : "false")
              << ",\"sourceConnect\":" << (source_connect ? "true" : "false")
              << ",\"firstFrame\":" << (first_frame ? "true" : "false")
              << ",\"outputReady\":" << (output_ready ? "true" : "false")
               << ",\"inferenceWindows\":" << inference_windows
               << ",\"reconnectOperations\":" << reconnect_operations
               << ",\"graphRebuildOperations\":" << graph_rebuild_operations
              << "}\n";
    if (!pass) return 1;

    const auto current_fds = settled_entry_count("/proc/self/fd");
    const auto current_threads = settled_entry_count("/proc/self/task");
    const auto current_gpu_bytes = used_gpu_bytes();
    if (cycle == 0) {
      baseline_fds = current_fds;
      baseline_threads = current_threads;
      baseline_gpu_bytes = current_gpu_bytes;
    } else if (current_fds > baseline_fds || current_threads > baseline_threads ||
               current_gpu_bytes > baseline_gpu_bytes) {
      std::cerr << "LIVE_SMOKE_RESOURCE_GROWTH baseline_fds=" << baseline_fds
                << " current_fds=" << current_fds
                << " baseline_threads=" << baseline_threads
                << " current_threads=" << current_threads
                << " baseline_gpu_bytes=" << baseline_gpu_bytes
                << " current_gpu_bytes=" << current_gpu_bytes << '\n';
      return 1;
    }
    }
    std::cout << "{\"cycles\":" << cycle_count
              << ",\"fds\":" << baseline_fds
              << ",\"threads\":" << baseline_threads
              << ",\"gpuBytes\":" << baseline_gpu_bytes << "}\n";
    return 0;
  } catch (const std::exception&) {
    std::cerr << "LIVE_SMOKE_FAILED\n";
    return 1;
  }
}
