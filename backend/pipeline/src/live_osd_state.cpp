#include "mvision/live_osd_state.hpp"

#include <algorithm>
#include <iomanip>
#include <numeric>
#include <sstream>

namespace mvision {

LiveOsdState::LiveOsdState(std::uint64_t generation) : generation_(generation) {}

bool LiveOsdState::apply(const IdentityAssignment& assignment) {
  if (assignment.header.generation != generation_) return false;
  auto& entry = entries_[assignment.tracker_id];
  if (!entry.identity.apply(assignment)) return false;
  entry.display_name = sanitize_name(assignment.display_name);
  entry.reference_embedding = assignment.reference_embedding;
  entry.recognition_threshold = assignment.recognition_threshold;
  entry.current_score.reset();
  entry.consecutive_high = 0;
  entry.consecutive_low = 0;
  entry.visible_known = assignment.identity_state == "known";
  return true;
}

bool LiveOsdState::observe(
    std::uint64_t tracker_id,
    const std::array<float, 512>& current_embedding) {
  const auto found = entries_.find(tracker_id);
  if (found == entries_.end()) return false;
  auto& entry = found->second;
  if (!entry.reference_embedding.has_value() ||
      !entry.recognition_threshold.has_value()) {
    return false;
  }
  const float score = std::clamp(
      std::inner_product(current_embedding.begin(), current_embedding.end(),
                         entry.reference_embedding->begin(), 0.0F),
      -1.0F, 1.0F);
  entry.current_score = score;
  if (score >= *entry.recognition_threshold) {
    entry.consecutive_low = 0;
    entry.consecutive_high =
        std::min<std::uint8_t>(3, entry.consecutive_high + 1);
    if (entry.consecutive_high == 3) entry.visible_known = true;
  } else {
    entry.consecutive_high = 0;
    entry.consecutive_low =
        std::min<std::uint8_t>(3, entry.consecutive_low + 1);
    if (entry.consecutive_low == 3) entry.visible_known = false;
  }
  return true;
}

std::string LiveOsdState::label(std::uint64_t tracker_id,
                                float detector_confidence) const {
  std::ostringstream output;
  output << std::fixed << std::setprecision(3);
  const auto found = entries_.find(tracker_id);
  if (found == entries_.end() ||
      found->second.identity.state() == TrackIdentityState::Pending) {
    output << "Pending det=" << detector_confidence;
    return output.str();
  }
  const auto& entry = found->second;
  if (entry.identity.state() == TrackIdentityState::Known && entry.visible_known) {
    output << (entry.display_name.empty() ? "Known" : entry.display_name) << "  ";
  } else {
    output << "Unknown ";
  }
  if (entry.current_score.has_value()) output << "cos=" << *entry.current_score << ' ';
  output << "det=" << detector_confidence;
  return output.str();
}

void LiveOsdState::expire(std::uint64_t generation, std::uint64_t tracker_id) {
  if (generation == generation_) entries_.erase(tracker_id);
}

void LiveOsdState::clear() { entries_.clear(); }

std::string LiveOsdState::sanitize_name(
    const std::optional<std::string>& name) {
  if (!name.has_value()) return {};
  std::string result;
  result.reserve(std::min<std::size_t>(80, name->size()));
  for (const unsigned char character : *name) {
    if (character < 0x20U || character == 0x7FU) continue;
    result.push_back(static_cast<char>(character));
    if (result.size() == 80) break;
  }
  return result;
}

}  // namespace mvision
