#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace mvision {

class PersistentJpegPipeline final {
 public:
  PersistentJpegPipeline(int gpu_id, std::uint32_t batch_size);
  ~PersistentJpegPipeline();

  PersistentJpegPipeline(const PersistentJpegPipeline &) = delete;
  PersistentJpegPipeline &operator=(const PersistentJpegPipeline &) = delete;

  void start();
  void push_jpeg(const std::vector<std::uint8_t> &jpeg, std::uint64_t pts_token);
  bool wait_for_frames(std::size_t count, std::chrono::milliseconds timeout);
  std::size_t source_slot_count() const noexcept;
  void close() noexcept;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace mvision
