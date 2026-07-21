#include "mvision/video_pipeline.hpp"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                  \
  do {                                                                     \
    if (!(condition)) throw std::runtime_error("assertion failed: " #condition); \
  } while (false)
#endif

namespace {

std::array<float, 512> unit(std::size_t index) {
  std::array<float, 512> value{};
  value[index] = 1.0F;
  return value;
}

}  // namespace

int main() {
  int first_object = 0;
  int second_object = 0;
  std::vector<float> output_rows(2 * 512, 0.0F);
  output_rows[0] = 3.0F;
  output_rows[512 + 1] = 4.0F;
  const auto mapped = mvision::map_embedding_rows(
      output_rows.data(), 2, {&first_object, &second_object});
  assert(mapped.has_value());
  assert(mapped->at(&first_object)[0] == 1.0F);
  assert(mapped->at(&first_object)[1] == 0.0F);
  assert(mapped->at(&second_object)[0] == 0.0F);
  assert(mapped->at(&second_object)[1] == 1.0F);

  std::array<float, 10> landmarks{
      317.36328F, 245.97656F, 345.26562F, 250.35938F, 323.97852F,
      269.125F,   316.65625F, 284.0F,     339.15625F, 287.375F,
  };
  mvision::transform_landmarks_from_network(landmarks, 640, 640, 1920, 1080);
  assert(std::abs(landmarks[0] - 952.08984F) < 0.01F);
  assert(std::abs(landmarks[1] - 317.92969F) < 0.01F);

  mvision::VideoTrackAccumulator accumulator;

  mvision::VideoObservation later;
  later.tracker_id = 7;
  later.detection = {10, 0.4, 90.0F, 40.0F, 30.0F, 40.0F, 0.8F};
  later.embedding = unit(0);

  mvision::VideoObservation earlier;
  earlier.tracker_id = 7;
  earlier.detection = {5, 0.2, -5.0F, -2.0F, 20.0F, 30.0F, 0.9F};
  earlier.embedding = unit(1);
  earlier.representative_jpeg = {0xFF, 0xD8, 0xFF, 0xD9};

  accumulator.add(later, 100, 80);
  accumulator.add(earlier, 100, 80);
  const auto tracks = accumulator.finish();

  assert(tracks.size() == 1);
  assert(tracks[0].tracker_id == 7);
  assert(tracks[0].detections.size() == 2);
  assert(tracks[0].detections[0].frame == 5);
  assert(tracks[0].detections[0].x == 0.0F);
  assert(tracks[0].detections[0].y == 0.0F);
  assert(tracks[0].detections[0].width == 15.0F);
  const float expected = 1.0F / std::sqrt(2.0F);
  assert(std::abs(tracks[0].embedding[0] - expected) < 1e-5F);
  assert(std::abs(tracks[0].embedding[1] - expected) < 1e-5F);
  assert(!tracks[0].representative_jpeg.empty());

  mvision::VideoObservation second_track;
  second_track.tracker_id = 3;
  second_track.detection = {20, 0.8, 1.0F, 1.0F, 2.0F, 2.0F, 0.7F};
  second_track.embedding = unit(2);
  accumulator.add(second_track, 100, 80);
  const auto sorted = accumulator.finish();
  assert(sorted.size() == 2);
  assert(sorted[0].tracker_id == 7);
  assert(sorted[1].tracker_id == 3);

  mvision::VideoTrackAccumulator quality_accumulator;
  for (std::uint64_t frame = 0; frame < 5; ++frame) {
    mvision::VideoObservation sharp;
    sharp.tracker_id = 9;
    sharp.detection = {frame, static_cast<double>(frame), 5.0F, 5.0F,
                       80.0F, 80.0F, 0.9F};
    sharp.embedding = unit(0);
    quality_accumulator.add(sharp, 100, 100);
  }
  mvision::VideoObservation poor;
  poor.tracker_id = 9;
  poor.detection = {6, 6.0, 5.0F, 5.0F, 20.0F, 20.0F, 0.2F};
  poor.embedding = unit(1);
  quality_accumulator.add(poor, 100, 100);
  const auto quality_tracks = quality_accumulator.finish();
  assert(quality_tracks.size() == 1);
  assert(std::abs(quality_tracks[0].embedding[0] - 1.0F) < 1e-5F);
  assert(std::abs(quality_tracks[0].embedding[1]) < 1e-5F);
  return 0;
}
