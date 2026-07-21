#include "mvision/video_pipeline.hpp"
#include "mvision/video_protocol.hpp"

#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>

namespace {

std::atomic_bool cancellation_requested{false};
int protocol_fd{-1};

void handle_signal(int) { cancellation_requested.store(true); }

void configure_protocol_output() {
  std::fflush(stdout);
  protocol_fd = dup(STDOUT_FILENO);
  if (protocol_fd < 0 || dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
    throw std::runtime_error("failed to isolate video protocol output");
  }
}

void write_event(const std::vector<std::uint8_t>& frame) {
  std::size_t written = 0;
  while (written < frame.size()) {
    const ssize_t count =
        write(protocol_fd, frame.data() + written, frame.size() - written);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      throw std::runtime_error("failed to write video event");
    }
    written += static_cast<std::size_t>(count);
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 12) {
    std::fprintf(stderr,
                 "usage: %s <video> <gpu-id> <sample-every-n> <width> <height> "
                 "<total-frames> <fps> <tracker> <pgie> <preprocess> <sgie>\n",
                 argv[0]);
    return 2;
  }
  std::signal(SIGTERM, handle_signal);
  std::signal(SIGINT, handle_signal);
  try {
    configure_protocol_output();
    mvision::VideoPipelineOptions options;
    options.video_path = argv[1];
    options.gpu_id = std::stoi(argv[2]);
    options.sample_every_n = static_cast<std::uint32_t>(std::stoul(argv[3]));
    options.width = static_cast<std::uint32_t>(std::stoul(argv[4]));
    options.height = static_cast<std::uint32_t>(std::stoul(argv[5]));
    options.total_frames = std::stoull(argv[6]);
    options.fps = std::stod(argv[7]);
    options.tracker_config_path = argv[8];
    options.pgie_config_path = argv[9];
    options.preprocess_config_path = argv[10];
    options.sgie_config_path = argv[11];
    mvision::DeepStreamVideoPipeline pipeline(std::move(options));
    pipeline.run(write_event, cancellation_requested);
    return cancellation_requested.load() ? 3 : 0;
  } catch (const std::exception& error) {
    try {
      write_event(mvision::encode_video_event(
          mvision::VideoFailed{"VIDEO_PIPELINE_ERROR", error.what()}));
    } catch (...) {
    }
    std::fprintf(stderr, "video pipeline failed: %s\n", error.what());
    return 1;
  }
}
