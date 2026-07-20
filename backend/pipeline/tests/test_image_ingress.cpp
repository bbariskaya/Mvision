#include "mvision/image_source_pool.hpp"

#include <cuda_runtime_api.h>

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc, char **argv) {
  if (argc != 2) {
    throw std::runtime_error("usage: test_image_ingress JPEG_PATH");
  }

  std::ifstream input(argv[1], std::ios::binary);
  const std::vector<std::uint8_t> jpeg{std::istreambuf_iterator<char>(input), {}};
  if (jpeg.empty() || cudaSetDevice(0) != cudaSuccess) {
    return 1;
  }

  mvision::PersistentJpegPipeline pipeline(0, 4);
  if (pipeline.source_slot_count() != 4) {
    return 1;
  }
  pipeline.start();
  for (std::uint64_t token = 1; token <= 8; ++token) {
    pipeline.push_jpeg(jpeg, token);
  }

  if (!pipeline.wait_for_frames(8, std::chrono::seconds(10))) {
    return 1;
  }
  pipeline.close();
  return 0;
}
