#pragma once

#include "mvision/video_protocol.hpp"

#include <array>
#include <atomic>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace mvision {

using ObjectEmbeddingMap =
    std::unordered_map<const void*, std::array<float, 512>>;

std::optional<ObjectEmbeddingMap> map_embedding_rows(
    const float* output, std::size_t row_count,
    const std::vector<const void*>& objects);

void transform_landmarks_from_network(std::array<float, 10>& landmarks,
                                      std::uint32_t network_width,
                                      std::uint32_t network_height,
                                      std::uint32_t frame_width,
                                      std::uint32_t frame_height);

struct VideoObservation {
  std::uint64_t tracker_id{};
  VideoDetection detection{};
  std::array<float, 512> embedding{};
  std::vector<std::uint8_t> representative_jpeg;
};

class VideoTrackAccumulator {
 public:
  void add(const VideoObservation& observation, std::uint32_t frame_width,
           std::uint32_t frame_height);
  std::vector<VideoTrackOutput> finish() const;

  private:
  struct RankedEmbedding {
    float quality{};
    std::uint64_t frame{};
    std::array<float, 512> embedding{};
  };

  struct TrackState {
    std::uint64_t tracker_id{};
    std::vector<RankedEmbedding> ranked_embeddings;
    float representative_score{-1.0F};
    std::vector<std::uint8_t> representative_jpeg;
    std::vector<VideoDetection> detections;
  };

  std::unordered_map<std::uint64_t, TrackState> tracks_;
};

struct VideoPipelineOptions {
  std::string video_path;
  int gpu_id{};
  std::uint32_t sample_every_n{1};
  std::uint32_t width{};
  std::uint32_t height{};
  std::uint64_t total_frames{};
  double fps{};
  std::string tracker_config_path;
  std::string pgie_config_path;
  std::string preprocess_config_path;
  std::string sgie_config_path;
};

using VideoEventCallback = std::function<void(const std::vector<std::uint8_t>&)>;

class DeepStreamVideoPipeline {
 public:
  explicit DeepStreamVideoPipeline(VideoPipelineOptions options);
  ~DeepStreamVideoPipeline();

  DeepStreamVideoPipeline(const DeepStreamVideoPipeline&) = delete;
  DeepStreamVideoPipeline& operator=(const DeepStreamVideoPipeline&) = delete;

  void run(const VideoEventCallback& callback, std::atomic_bool& cancellation_requested);

 private:
  class Impl;
  Impl* impl_;
};

}  // namespace mvision
