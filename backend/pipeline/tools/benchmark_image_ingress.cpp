#include "mvision/image_source_pool.hpp"

#include <cuda_runtime_api.h>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char **argv) {
  if (argc != 4) {
    std::cerr << "usage: benchmark_image_ingress JPEG_PATH IMAGE_COUNT SOURCE_SLOTS\n";
    return 2;
  }

  std::ifstream input(argv[1], std::ios::binary);
  const std::vector<std::uint8_t> jpeg{std::istreambuf_iterator<char>(input), {}};
  const auto image_count = std::stoull(argv[2]);
  const auto source_slots = static_cast<std::uint32_t>(std::stoul(argv[3]));
  if (jpeg.empty() || image_count == 0 || source_slots == 0 || cudaSetDevice(0) != cudaSuccess) {
    throw std::runtime_error("invalid benchmark input");
  }

  mvision::PersistentJpegPipeline pipeline(0, source_slots);
  pipeline.start();

  const auto started_at = std::chrono::steady_clock::now();
  for (std::uint64_t token = 1; token <= image_count; ++token) {
    pipeline.push_jpeg(jpeg, token);
  }
  if (!pipeline.wait_for_frames(image_count, std::chrono::seconds(60))) {
    throw std::runtime_error("timed out waiting for GPU ingress");
  }
  const auto finished_at = std::chrono::steady_clock::now();
  pipeline.close();

  const std::chrono::duration<double> elapsed = finished_at - started_at;
  const double fps = static_cast<double>(image_count) / elapsed.count();
  std::cout << std::fixed << std::setprecision(2) << "images=" << image_count
            << " slots=" << source_slots << " seconds=" << elapsed.count() << " fps=" << fps
            << '\n';
  return 0;
}
