#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace mvision {

struct IdentityAssignment;

inline constexpr std::uint64_t kRejectGeometry = 1ULL << 0U;
inline constexpr std::uint64_t kRejectLandmarks = 1ULL << 1U;
inline constexpr std::uint64_t kRejectEmbedding = 1ULL << 2U;
inline constexpr std::uint64_t kRejectSnapshotSize = 1ULL << 3U;
inline constexpr std::uint64_t kRejectDetectorConfidence = 1ULL << 4U;
inline constexpr std::uint64_t kRejectFaceSize = 1ULL << 5U;
inline constexpr std::uint64_t kRejectPose = 1ULL << 6U;
inline constexpr std::uint64_t kRejectExposure = 1ULL << 7U;
inline constexpr std::uint64_t kRejectSharpness = 1ULL << 8U;
inline constexpr std::uint64_t kRejectClipping = 1ULL << 9U;

struct QualityConfig {
  // Candidate thresholds stay shadow-only until live calibration proves them.
  float geometry_tolerance = 0.05F;
  float target_area_ratio = 0.10F;
  float min_face_area_ratio = 0.0025F;
  float min_detector_confidence = 0.50F;
  float min_pose_weight = 0.30F;
  float min_exposure_weight = 0.30F;
  float min_sharpness_weight = 0.30F;
  float near_pose_degrees = 15.0F;
  float replacement_margin = 0.05F;
  bool shadow_mode = true;
};

struct QualityMeasurement {
  float face_area_ratio{};
  float quality_score{};
  std::uint64_t reject_mask{};
  bool hard_reject{};
  bool accepted{};
};

struct LiveObservation {
  std::uint64_t timestamp_ns{};
  std::uint64_t detection_ordinal{};
  std::uint32_t frame_width{};
  std::uint32_t frame_height{};
  std::array<float, 4> bbox{};
  float detector_confidence{};
  float pose_yaw_degrees{};
  float pose_weight{1.0F};
  float exposure_weight{1.0F};
  float sharpness_weight{1.0F};
  std::array<float, 10> landmarks{};
  std::array<float, 5> landmark_confidences{};
  std::array<float, 512> embedding{};
  std::vector<std::byte> aligned_jpeg;
  QualityMeasurement quality{};
};

QualityMeasurement measure_quality(const LiveObservation& observation,
                                   const QualityConfig& config);

enum class EvidenceChange { Rejected, Unchanged, Added, Replaced };

class TrackEvidenceBank {
 public:
  TrackEvidenceBank(std::size_t capacity, std::uint64_t min_spacing_ns,
                    QualityConfig config = {});

  EvidenceChange consider(const LiveObservation& observation);
  const std::vector<LiveObservation>& observations() const noexcept;
  std::size_t storage_capacity() const noexcept;
  void expire();

 private:
  bool better(const LiveObservation& candidate,
              const LiveObservation& current) const;
  void sort_observations();

  std::size_t capacity_;
  std::uint64_t min_spacing_ns_;
  QualityConfig config_;
  std::vector<LiveObservation> observations_;
};

enum class TrackIdentityState { Pending, Known, Unknown };

class IdentityAssignmentState {
 public:
  bool apply(const IdentityAssignment& assignment);
  TrackIdentityState state() const noexcept;
  const std::optional<std::string>& face_id() const noexcept;
  std::uint64_t revision() const noexcept;

 private:
  TrackIdentityState state_ = TrackIdentityState::Pending;
  std::optional<std::string> face_id_;
  std::uint64_t revision_{};
  std::uint64_t identity_epoch_{1};
};

}  // namespace mvision
