#include "mvision/live_track_state.hpp"
#include "mvision/live_protocol.hpp"

#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                        \
  do {                                                                           \
    if (!(condition)) throw std::runtime_error("assertion failed: " #condition); \
  } while (false)
#endif

namespace {

constexpr const char* kCameraId = "019b0000-0000-7000-8000-000000000001";
constexpr const char* kRunId = "019b0000-0000-7000-8000-000000000002";
constexpr const char* kFaceA = "019b0000-0000-7000-8000-000000000003";
constexpr const char* kFaceB = "019b0000-0000-7000-8000-000000000004";

mvision::ProtocolHeader assignment_header(std::uint64_t sequence) {
  return {1,
          "identity_assignment",
          kCameraId,
          kRunId,
          1,
          sequence,
          "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
          std::nullopt};
}

mvision::LiveObservation observation(std::uint64_t timestamp_ns,
                                     float quality_seed = 0.9F,
                                     float yaw_degrees = 0.0F,
                                     std::uint64_t ordinal = 1) {
  mvision::LiveObservation value;
  value.timestamp_ns = timestamp_ns;
  value.detection_ordinal = ordinal;
  value.frame_width = 1920;
  value.frame_height = 1080;
  value.bbox = {100.0F, 100.0F, 300.0F, 300.0F};
  value.detector_confidence = quality_seed;
  value.pose_yaw_degrees = yaw_degrees;
  value.pose_weight = quality_seed;
  value.exposure_weight = quality_seed;
  value.sharpness_weight = quality_seed;
  value.landmarks = {130.0F, 150.0F, 250.0F, 150.0F, 190.0F,
                     200.0F, 145.0F, 250.0F, 235.0F, 250.0F};
  value.landmark_confidences.fill(0.9F);
  value.embedding.fill(0.0F);
  value.embedding[0] = 1.0F;
  value.aligned_jpeg = {std::byte{0xFF}, std::byte{0xD8}, std::byte{0xFF},
                        std::byte{0xD9}};
  return value;
}

void test_quality_formula_and_shadow_rejects() {
  mvision::QualityConfig config;
  config.target_area_ratio = 0.10F;
  config.min_detector_confidence = 0.80F;
  config.shadow_mode = true;
  auto value = observation(1, 0.5F);
  value.bbox = {0.0F, 0.0F, 192.0F, 108.0F};

  const auto quality = mvision::measure_quality(value, config);

  const auto expected = 0.5F * std::sqrt(0.01F) / 0.10F * 0.5F * 0.5F * 0.5F;
  assert(std::fabs(quality.quality_score - expected) < 1e-6F);
  assert((quality.reject_mask & mvision::kRejectDetectorConfidence) != 0);
  assert(!quality.hard_reject);
  assert(quality.accepted);
}

void test_near_time_and_view_keeps_only_the_better_observation() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  bank.consider(observation(1'000'000'000, 0.7F));
  const auto change = bank.consider(observation(1'050'000'000, 0.9F));

  assert(change == mvision::EvidenceChange::Replaced);
  assert(bank.observations().size() == 1);
  assert(bank.observations().front().quality.quality_score > 0.5F);
}

void test_time_spaced_different_views_coexist_and_capacity_is_bounded() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  for (std::uint64_t index = 0; index < 100; ++index) {
    bank.consider(observation(index * 300'000'000, 0.8F,
                              static_cast<float>(index % 7) * 10.0F, index));
    assert(bank.observations().size() <= 10);
  }
  assert(bank.observations().size() == 10);
}

void test_invalid_embedding_geometry_and_landmarks_are_hard_rejected() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  auto invalid_embedding = observation(1);
  invalid_embedding.embedding.fill(0.0F);
  assert(bank.consider(invalid_embedding) == mvision::EvidenceChange::Rejected);

  auto non_finite = observation(2);
  non_finite.embedding[0] = std::numeric_limits<float>::infinity();
  assert(bank.consider(non_finite) == mvision::EvidenceChange::Rejected);

  auto invalid_bbox = observation(3);
  invalid_bbox.bbox = {-500.0F, 0.0F, 100.0F, 100.0F};
  const auto bbox_quality = mvision::measure_quality(invalid_bbox, {});
  assert(bbox_quality.hard_reject);
  assert((bbox_quality.reject_mask & mvision::kRejectGeometry) != 0);

  auto invalid_landmarks = observation(4);
  invalid_landmarks.landmarks[0] = 4000.0F;
  const auto landmark_quality = mvision::measure_quality(invalid_landmarks, {});
  assert(landmark_quality.hard_reject);
  assert((landmark_quality.reject_mask & mvision::kRejectLandmarks) != 0);
}

void test_equal_quality_ties_break_by_timestamp_then_ordinal() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  bank.consider(observation(1'100'000'000, 0.9F, 0.0F, 9));
  bank.consider(observation(1'000'000'000, 0.9F, 0.0F, 8));
  assert(bank.observations().front().timestamp_ns == 1'000'000'000);
  bank.consider(observation(1'000'000'000, 0.9F, 0.0F, 2));
  assert(bank.observations().front().detection_ordinal == 2);
}

void test_non_shadow_soft_reject_is_excluded() {
  mvision::QualityConfig config;
  config.shadow_mode = false;
  config.min_detector_confidence = 0.8F;
  mvision::TrackEvidenceBank bank(10, 200'000'000, config);
  assert(bank.consider(observation(1, 0.5F)) ==
         mvision::EvidenceChange::Rejected);
}

void test_expire_releases_observation_and_jpeg_capacity() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  bank.consider(observation(1));
  assert(bank.storage_capacity() >= 1);
  bank.expire();
  assert(bank.observations().empty());
  assert(bank.storage_capacity() == 0);
}

mvision::IdentityAssignment assignment(std::uint64_t revision,
                                       std::string state,
                                       const char* face_id,
                                       std::uint64_t identity_epoch = 1) {
  std::optional<std::array<float, 512>> reference;
  if (face_id != nullptr) {
    std::array<float, 512> value{};
    value[0] = 1.0F;
    reference = value;
  }
  return {assignment_header(revision),
          42,
          revision,
          identity_epoch,
          std::move(state),
          face_id == nullptr ? std::nullopt
                             : std::optional<std::string>("Ada"),
          face_id == nullptr ? std::nullopt
                             : std::optional<std::string>(face_id),
           face_id == nullptr ? std::nullopt : std::optional<float>(0.9F),
           face_id == nullptr ? std::nullopt : std::optional<float>(0.8F),
           reference,
           revision};
}

void test_identity_assignment_is_revisioned_and_known_is_immutable() {
  mvision::IdentityAssignmentState state;
  assert(state.apply(assignment(1, "known", kFaceA)));
  assert(state.state() == mvision::TrackIdentityState::Known);
  assert(state.face_id() == std::optional<std::string>(kFaceA));
  assert(!state.apply(assignment(2, "known", kFaceB)));
  assert(!state.apply(assignment(3, "unknown", nullptr)));
  assert(!state.apply(assignment(1, "known", kFaceA)));
  assert(state.face_id() == std::optional<std::string>(kFaceA));
  assert(state.apply(assignment(4, "unknown", nullptr, 2)));
  assert(state.state() == mvision::TrackIdentityState::Unknown);
  assert(state.apply(assignment(5, "known", kFaceB, 2)));
  assert(!state.apply(assignment(6, "known", kFaceA, 1)));
  assert(state.face_id() == std::optional<std::string>(kFaceB));
}

void run_stress() {
  mvision::TrackEvidenceBank bank(10, 200'000'000);
  for (std::uint64_t index = 0; index < 100'000; ++index) {
    bank.consider(observation(index * 1'000'000, 0.7F + (index % 20) * 0.01F,
                              static_cast<float>(index % 9) * 8.0F, index));
    assert(bank.observations().size() <= 10);
  }
}

}  // namespace

int main(int argc, char** argv) {
  test_quality_formula_and_shadow_rejects();
  test_near_time_and_view_keeps_only_the_better_observation();
  test_time_spaced_different_views_coexist_and_capacity_is_bounded();
  test_invalid_embedding_geometry_and_landmarks_are_hard_rejected();
  test_equal_quality_ties_break_by_timestamp_then_ordinal();
  test_non_shadow_soft_reject_is_excluded();
  test_expire_releases_observation_and_jpeg_capacity();
  test_identity_assignment_is_revisioned_and_known_is_immutable();
  if (argc == 2 && std::string(argv[1]) == "--stress") run_stress();
  return 0;
}
