#include "mvision/live_track_state.hpp"

#include "mvision/live_protocol.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace mvision {
namespace {

float clamp_weight(float value) {
  if (!std::isfinite(value)) return 0.0F;
  return std::clamp(value, 0.0F, 1.0F);
}

template <typename Values>
bool finite_array(const Values& values) {
  return std::all_of(values.begin(), values.end(),
                     [](float value) { return std::isfinite(value); });
}

std::uint64_t distance(std::uint64_t left, std::uint64_t right) {
  return left >= right ? left - right : right - left;
}

}  // namespace

QualityMeasurement measure_quality(const LiveObservation& observation,
                                   const QualityConfig& config) {
  QualityMeasurement result;
  const bool dimensions_valid = observation.frame_width > 0 && observation.frame_height > 0;
  const float frame_width = static_cast<float>(observation.frame_width);
  const float frame_height = static_cast<float>(observation.frame_height);
  const float x = observation.bbox[0];
  const float y = observation.bbox[1];
  const float width = observation.bbox[2];
  const float height = observation.bbox[3];
  const float x_tolerance = frame_width * config.geometry_tolerance;
  const float y_tolerance = frame_height * config.geometry_tolerance;
  const bool geometry_valid =
      dimensions_valid && finite_array(observation.bbox) && width > 0.0F &&
      height > 0.0F && x >= -x_tolerance && y >= -y_tolerance &&
      x + width <= frame_width + x_tolerance &&
      y + height <= frame_height + y_tolerance;
  if (!geometry_valid) {
    result.reject_mask |= kRejectGeometry;
    result.hard_reject = true;
  }

  bool landmarks_valid = finite_array(observation.landmarks) && dimensions_valid;
  if (landmarks_valid) {
    for (std::size_t index = 0; index < observation.landmarks.size(); index += 2) {
      const float landmark_x = observation.landmarks[index];
      const float landmark_y = observation.landmarks[index + 1];
      if (landmark_x < -x_tolerance || landmark_x > frame_width + x_tolerance ||
          landmark_y < -y_tolerance || landmark_y > frame_height + y_tolerance) {
        landmarks_valid = false;
        break;
      }
    }
  }
  if (!landmarks_valid) {
    result.reject_mask |= kRejectLandmarks;
    result.hard_reject = true;
  }

  bool embedding_valid = finite_array(observation.embedding);
  double squared_norm = 0.0;
  if (embedding_valid) {
    for (const float value : observation.embedding) {
      squared_norm += static_cast<double>(value) * static_cast<double>(value);
    }
    const double norm = std::sqrt(squared_norm);
    embedding_valid = norm >= 0.99 && norm <= 1.01;
  }
  if (!embedding_valid) {
    result.reject_mask |= kRejectEmbedding;
    result.hard_reject = true;
  }
  if (observation.aligned_jpeg.size() > kMaxAlignedJpegBytes) {
    result.reject_mask |= kRejectSnapshotSize;
    result.hard_reject = true;
  }

  if (geometry_valid) {
    result.face_area_ratio =
        width * height / (frame_width * frame_height);
    const bool clipped = x < 0.0F || y < 0.0F || x + width > frame_width ||
                         y + height > frame_height;
    if (clipped) result.reject_mask |= kRejectClipping;
  }
  if (!std::isfinite(observation.detector_confidence) ||
      observation.detector_confidence < config.min_detector_confidence) {
    result.reject_mask |= kRejectDetectorConfidence;
  }
  if (result.face_area_ratio < config.min_face_area_ratio) {
    result.reject_mask |= kRejectFaceSize;
  }
  if (clamp_weight(observation.pose_weight) < config.min_pose_weight) {
    result.reject_mask |= kRejectPose;
  }
  if (clamp_weight(observation.exposure_weight) < config.min_exposure_weight) {
    result.reject_mask |= kRejectExposure;
  }
  if (clamp_weight(observation.sharpness_weight) < config.min_sharpness_weight) {
    result.reject_mask |= kRejectSharpness;
  }

  const float area_weight = config.target_area_ratio > 0.0F
                                ? std::clamp(std::sqrt(std::max(0.0F, result.face_area_ratio)) /
                                                 config.target_area_ratio,
                                             0.0F, 1.0F)
                                : 0.0F;
  result.quality_score =
      clamp_weight(observation.detector_confidence) * area_weight *
      clamp_weight(observation.pose_weight) *
      clamp_weight(observation.exposure_weight) *
      clamp_weight(observation.sharpness_weight);
  const std::uint64_t soft_mask =
      kRejectDetectorConfidence | kRejectFaceSize | kRejectPose | kRejectExposure |
      kRejectSharpness | kRejectClipping;
  result.accepted = !result.hard_reject &&
                    (config.shadow_mode || (result.reject_mask & soft_mask) == 0);
  return result;
}

TrackEvidenceBank::TrackEvidenceBank(std::size_t capacity,
                                     std::uint64_t min_spacing_ns,
                                     QualityConfig config)
    : capacity_(capacity),
      min_spacing_ns_(min_spacing_ns),
      config_(config) {
  observations_.reserve(capacity_);
}

bool TrackEvidenceBank::better(const LiveObservation& candidate,
                               const LiveObservation& current) const {
  if (candidate.quality.quality_score != current.quality.quality_score) {
    return candidate.quality.quality_score > current.quality.quality_score;
  }
  if (candidate.timestamp_ns != current.timestamp_ns) {
    return candidate.timestamp_ns < current.timestamp_ns;
  }
  return candidate.detection_ordinal < current.detection_ordinal;
}

void TrackEvidenceBank::sort_observations() {
  std::sort(observations_.begin(), observations_.end(),
            [this](const auto& left, const auto& right) { return better(left, right); });
}

EvidenceChange TrackEvidenceBank::consider(const LiveObservation& observation) {
  auto candidate = observation;
  candidate.quality = measure_quality(candidate, config_);
  if (!candidate.quality.accepted || capacity_ == 0) return EvidenceChange::Rejected;

  const auto near = std::find_if(
      observations_.begin(), observations_.end(), [&](const auto& current) {
        return distance(candidate.timestamp_ns, current.timestamp_ns) <= min_spacing_ns_ &&
               std::fabs(candidate.pose_yaw_degrees - current.pose_yaw_degrees) <=
                   config_.near_pose_degrees;
      });
  if (near != observations_.end()) {
    if (!better(candidate, *near)) return EvidenceChange::Unchanged;
    *near = std::move(candidate);
    sort_observations();
    return EvidenceChange::Replaced;
  }

  if (observations_.size() < capacity_) {
    observations_.push_back(std::move(candidate));
    sort_observations();
    return EvidenceChange::Added;
  }

  auto worst = std::prev(observations_.end());
  const bool increases_diversity = std::all_of(
      observations_.begin(), observations_.end(), [&](const auto& current) {
        return std::fabs(candidate.pose_yaw_degrees - current.pose_yaw_degrees) >
               config_.near_pose_degrees;
      });
  const bool clears_margin = candidate.quality.quality_score >=
                             worst->quality.quality_score + config_.replacement_margin;
  if (!better(candidate, *worst) || (!increases_diversity && !clears_margin)) {
    return EvidenceChange::Unchanged;
  }
  *worst = std::move(candidate);
  sort_observations();
  return EvidenceChange::Replaced;
}

const std::vector<LiveObservation>& TrackEvidenceBank::observations() const noexcept {
  return observations_;
}

std::size_t TrackEvidenceBank::storage_capacity() const noexcept {
  return observations_.capacity();
}

void TrackEvidenceBank::expire() {
  std::vector<LiveObservation>().swap(observations_);
}

bool IdentityAssignmentState::apply(const IdentityAssignment& assignment) {
  if (assignment.assignment_revision <= revision_) return false;
  if (assignment.identity_epoch < identity_epoch_) return false;
  if (assignment.identity_state != "known" && assignment.identity_state != "unknown") {
    return false;
  }
  if (assignment.identity_epoch > identity_epoch_) {
    if (assignment.identity_state != "unknown") return false;
    identity_epoch_ = assignment.identity_epoch;
    state_ = TrackIdentityState::Pending;
    face_id_.reset();
  }
  if (state_ == TrackIdentityState::Known) {
    if (assignment.identity_state != "known" || assignment.face_id != face_id_) return false;
  }
  if (assignment.identity_state == "known") {
    if (!assignment.face_id.has_value()) return false;
    state_ = TrackIdentityState::Known;
    face_id_ = assignment.face_id;
  } else {
    state_ = TrackIdentityState::Unknown;
    face_id_.reset();
  }
  revision_ = assignment.assignment_revision;
  return true;
}

TrackIdentityState IdentityAssignmentState::state() const noexcept { return state_; }

const std::optional<std::string>& IdentityAssignmentState::face_id() const noexcept {
  return face_id_;
}

std::uint64_t IdentityAssignmentState::revision() const noexcept { return revision_; }

}  // namespace mvision
