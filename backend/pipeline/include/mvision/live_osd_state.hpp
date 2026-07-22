#pragma once

#include "mvision/live_protocol.hpp"
#include "mvision/live_track_state.hpp"

#include <cstdint>
#include <string>
#include <unordered_map>

namespace mvision {

class LiveOsdState {
 public:
  explicit LiveOsdState(std::uint64_t generation);

  bool apply(const IdentityAssignment& assignment);
  bool observe(std::uint64_t tracker_id,
               const std::array<float, 512>& current_embedding);
  std::string label(std::uint64_t tracker_id, float detector_confidence) const;
  void expire(std::uint64_t generation, std::uint64_t tracker_id);
  void clear();

 private:
  struct Entry {
    IdentityAssignmentState identity;
    std::string display_name;
    std::optional<std::array<float, 512>> reference_embedding;
    std::optional<float> recognition_threshold;
    std::optional<float> current_score;
    bool visible_known{false};
    std::uint8_t consecutive_high{};
    std::uint8_t consecutive_low{};
  };

  static std::string sanitize_name(const std::optional<std::string>& name);

  std::uint64_t generation_;
  std::unordered_map<std::uint64_t, Entry> entries_;
};

}  // namespace mvision
