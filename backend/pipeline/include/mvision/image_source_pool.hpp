#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace mvision {

struct FaceDetection {
  float left;
  float top;
  float width;
  float height;
  float confidence;
  std::array<float, 10> landmarks_xy;
  std::array<float, 512> embedding;
  std::vector<std::uint8_t> aligned_jpeg;
};

struct ImageDetectionResult {
  std::uint32_t source_id;
  std::uint64_t pts_token;
  std::uint32_t original_width;
  std::uint32_t original_height;
  std::vector<FaceDetection> faces;
};

class PersistentJpegPipeline final {
 public:
  PersistentJpegPipeline(int gpu_id, std::uint32_t batch_size,
                         std::string pgie_config_path = {},
                         std::string preprocess_config_path = {},
                         std::string sgie_config_path = {});
  ~PersistentJpegPipeline();

  PersistentJpegPipeline(const PersistentJpegPipeline &) = delete;
  PersistentJpegPipeline &operator=(const PersistentJpegPipeline &) = delete;

  void start();
  void begin_batch();
  void push_jpeg(const std::vector<std::uint8_t> &jpeg, std::uint64_t pts_token);
  bool wait_for_frames(std::size_t count, std::chrono::milliseconds timeout);
  std::vector<ImageDetectionResult> take_results();
  std::size_t preprocessed_face_count() const;
  std::size_t source_slot_count() const noexcept;
  void close() noexcept;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace mvision
