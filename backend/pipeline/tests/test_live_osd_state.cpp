#include "mvision/live_osd_state.hpp"

#include <cassert>
#include <cmath>
#include <optional>
#include <string>

namespace {

constexpr char kCameraId[] = "019b0000-0000-7000-8000-000000000001";
constexpr char kRunId[] = "019b0000-0000-7000-8000-000000000002";
constexpr char kFaceA[] = "019b0000-0000-7000-8000-000000000003";
constexpr char kFaceB[] = "019b0000-0000-7000-8000-000000000004";
constexpr char kTraceparent[] =
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

std::array<float, 512> embedding(float cosine) {
  std::array<float, 512> value{};
  value[0] = cosine;
  value[1] = std::sqrt(1.0F - cosine * cosine);
  return value;
}

mvision::IdentityAssignment assignment(std::uint64_t generation,
                                       std::uint64_t revision,
                                       std::uint64_t epoch,
                                       std::string state,
                                       std::optional<std::string> name,
                                        std::optional<std::string> face_id,
                                        std::optional<float> score) {
  const bool known = state == "known";
  return {{mvision::kLiveProtocolVersion, "identity_assignment", kCameraId,
           kCameraId, kRunId, generation, 1, revision, kTraceparent,
           std::nullopt},
          42,
          revision,
          epoch,
          std::move(state),
          std::move(name),
           std::move(face_id),
           score,
           known ? std::optional<float>(0.8F) : std::nullopt,
           known ? std::optional<std::array<float, 512>>(embedding(1.0F))
                 : std::nullopt,
           revision};
}

void test_exact_labels() {
  mvision::LiveOsdState known(1);
  assert(known.apply(
      assignment(1, 1, 1, "known", "Monica", kFaceA, 0.873F)));
  assert(known.observe(42, embedding(0.873F)));
  assert(known.label(42, 0.941F) == "Monica  cos=0.873 det=0.941");

  mvision::LiveOsdState unknown(1);
  assert(unknown.apply(assignment(1, 1, 1, "known", "Monica", kFaceA, 0.9F)));
  assert(unknown.observe(42, embedding(0.392F)));
  assert(unknown.observe(42, embedding(0.392F)));
  assert(unknown.observe(42, embedding(0.392F)));
  assert(unknown.label(42, 0.901F) == "Unknown cos=0.392 det=0.901");

  mvision::LiveOsdState pending(1);
  assert(pending.label(42, 0.901F) == "Pending det=0.901");
}

void test_fencing_epoch_reset_and_expiry() {
  mvision::LiveOsdState state(2);
  assert(!state.apply(
      assignment(1, 1, 1, "known", "Old", kFaceA, 0.99F)));
  assert(state.apply(
      assignment(2, 2, 1, "known", "Monica", kFaceA, 0.87F)));
  assert(state.observe(42, embedding(0.87F)));
  assert(!state.apply(
      assignment(2, 1, 1, "known", "Old", kFaceA, 0.99F)));
  assert(!state.apply(
      assignment(2, 3, 1, "known", "Rachel", kFaceB, 0.95F)));

  assert(state.apply(assignment(2, 4, 2, "unknown", std::nullopt,
                                std::nullopt, std::nullopt)));
  assert(state.label(42, 0.90F) == "Unknown det=0.900");
  assert(state.apply(
      assignment(2, 5, 2, "known", "Rachel", kFaceB, 0.92F)));
  assert(state.observe(42, embedding(0.92F)));
  assert(state.label(42, 0.90F) == "Rachel  cos=0.920 det=0.900");

  state.expire(2, 42);
  assert(state.label(42, 0.90F) == "Pending det=0.900");
}

void test_name_is_sanitized_and_capped() {
  mvision::LiveOsdState state(1);
  const std::string unsafe = "Mo\nni\tca" + std::string(100, 'x');
  assert(state.apply(
      assignment(1, 1, 1, "known", unsafe, kFaceA, 0.90F)));
  assert(state.observe(42, embedding(0.90F)));
  const auto label = state.label(42, 0.90F);
  assert(label.find('\n') == std::string::npos);
  assert(label.find('\t') == std::string::npos);
  assert(label.substr(0, label.find("  cos=")).size() == 80);
}

void test_current_frame_score_and_hysteresis() {
  mvision::LiveOsdState state(1);
  assert(state.apply(assignment(1, 1, 1, "known", "Baris", kFaceA, 0.9F)));
  assert(state.observe(42, embedding(0.91F)));
  assert(state.label(42, 0.8F) == "Baris  cos=0.910 det=0.800");
  assert(state.observe(42, embedding(0.83F)));
  assert(state.label(42, 0.8F) == "Baris  cos=0.830 det=0.800");
  assert(state.observe(42, embedding(0.3F)));
  assert(state.observe(42, embedding(0.3F)));
  assert(state.label(42, 0.8F) == "Baris  cos=0.300 det=0.800");
  assert(state.observe(42, embedding(0.3F)));
  assert(state.label(42, 0.8F) == "Unknown cos=0.300 det=0.800");
  assert(state.observe(42, embedding(0.9F)));
  assert(state.observe(42, embedding(0.9F)));
  assert(state.label(42, 0.8F) == "Unknown cos=0.900 det=0.800");
  assert(state.observe(42, embedding(0.9F)));
  assert(state.label(42, 0.8F) == "Baris  cos=0.900 det=0.800");
}

}  // namespace

int main() {
  test_exact_labels();
  test_fencing_epoch_reset_and_expiry();
  test_name_is_sanitized_and_capped();
  test_current_frame_score_and_hysteresis();
  return 0;
}
