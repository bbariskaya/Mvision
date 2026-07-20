#include "mvision/image_source_pool.hpp"

#include <cuda_runtime_api.h>

#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <iostream>
#include <stdexcept>
#include <vector>

int main(int argc, char **argv) {
  if (argc != 6) {
    throw std::runtime_error(
        "usage: test_detector_pipeline JPEG_PATH PGIE_CONFIG_PATH PREPROCESS_CONFIG_PATH "
        "SGIE_CONFIG_PATH EXPECTED_FACES");
  }
  std::ifstream input(argv[1], std::ios::binary);
  const std::vector<std::uint8_t> jpeg{std::istreambuf_iterator<char>(input), {}};
  if (jpeg.empty() || cudaSetDevice(0) != cudaSuccess) {
    return 1;
  }

  constexpr std::uint64_t kToken = 123456;
  const std::size_t expected_faces = std::stoull(argv[5]);
  mvision::PersistentJpegPipeline pipeline(0, 1, argv[2], argv[3], argv[4]);
  pipeline.start();
  pipeline.push_jpeg(jpeg, kToken);
  if (!pipeline.wait_for_frames(1, std::chrono::seconds(20))) {
    std::cerr << "timeout\n";
    return 1;
  }
  const auto results = pipeline.take_results();
  const auto preprocessed_faces = pipeline.preprocessed_face_count();
  pipeline.close();
  if (results.size() != 1 || results[0].pts_token != kToken ||
      results[0].faces.size() != expected_faces) {
    std::cerr << "result mismatch results=" << results.size()
              << " preprocessed=" << preprocessed_faces
              << " faces=" << (results.empty() ? 0 : results[0].faces.size()) << '\n';
    return 1;
  }
  if (preprocessed_faces != results[0].faces.size()) {
    std::cerr << "preprocess counter mismatch preprocessed=" << preprocessed_faces
              << " faces=" << results[0].faces.size() << '\n';
  }

  const auto &result = results[0];
  for (const auto &face : result.faces) {
    if (face.left < 0.0F || face.top < 0.0F || face.width <= 0.0F || face.height <= 0.0F ||
        face.left + face.width > result.original_width ||
        face.top + face.height > result.original_height || face.confidence < 0.25F) {
      std::cerr << "invalid detection\n";
      return 1;
    }
    float norm_squared = 0.0F;
    for (const float value : face.embedding) {
      if (!std::isfinite(value)) {
        std::cerr << "non-finite embedding\n";
        return 1;
      }
      norm_squared += value * value;
    }
    if (std::abs(std::sqrt(norm_squared) - 1.0F) > 1.0e-5F) {
      std::cerr << "embedding norm=" << std::sqrt(norm_squared) << '\n';
      return 1;
    }
    for (std::size_t coordinate = 0; coordinate < face.landmarks_xy.size(); coordinate += 2) {
      if (face.landmarks_xy[coordinate] < 0.0F ||
          face.landmarks_xy[coordinate] > result.original_width ||
          face.landmarks_xy[coordinate + 1] < 0.0F ||
          face.landmarks_xy[coordinate + 1] > result.original_height) {
        std::cerr << "invalid landmarks\n";
        return 1;
      }
    }
  }
  return 0;
}
