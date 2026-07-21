#include "mvision/image_source_pool.hpp"

#include <cuda_runtime_api.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

std::vector<std::uint8_t> read_image(const char *path) {
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input), {}};
}

int main(int argc, char **argv) {
  if (argc < 3) {
    std::cerr << "usage: inspect_detector_pipeline PGIE_CONFIG JPEG [JPEG ...]\n";
    return 2;
  }
  if (cudaSetDevice(0) != cudaSuccess) {
    return 1;
  }

  const auto image_count = static_cast<std::uint32_t>(argc - 2);
  mvision::PersistentJpegPipeline pipeline(0, image_count, argv[1]);
  pipeline.start();
  for (int index = 0; index < argc - 2; ++index) {
    const auto jpeg = read_image(argv[index + 2]);
    if (jpeg.empty()) {
      throw std::runtime_error(std::string("empty image: ") + argv[index + 2]);
    }
    pipeline.push_jpeg(jpeg, static_cast<std::uint64_t>(index + 1));
  }
  if (!pipeline.wait_for_frames(image_count, std::chrono::seconds(30))) {
    throw std::runtime_error("timed out waiting for detector results");
  }
  auto results = pipeline.take_results();
  pipeline.close();
  std::sort(results.begin(), results.end(), [](const auto &left, const auto &right) {
    return left.pts_token < right.pts_token;
  });

  std::cout << std::fixed << std::setprecision(2);
  for (const auto &result : results) {
    const char *path = argv[static_cast<int>(result.pts_token) + 1];
    std::cout << "image=" << path << " token=" << result.pts_token << " source=" << result.source_id
              << " size=" << result.original_width << 'x' << result.original_height
              << " faces=" << result.faces.size() << '\n';
    for (std::size_t index = 0; index < result.faces.size(); ++index) {
      const auto &face = result.faces[index];
      std::cout << "  face=" << index << " confidence=" << face.confidence << " bbox="
                << face.left << ',' << face.top << ',' << face.width << ',' << face.height << '\n';
    }
  }
  return results.size() == image_count ? 0 : 1;
}
