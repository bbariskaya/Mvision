#include "mvision/image_source_pool.hpp"
#include "mvision/protocol.hpp"

#include <arpa/inet.h>
#include <cuda_runtime_api.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

void read_exact(int fd, void *data, std::size_t size) {
  auto *bytes = static_cast<std::uint8_t *>(data);
  while (size > 0) {
    const ssize_t received = recv(fd, bytes, size, 0);
    if (received <= 0) {
      throw std::runtime_error("socket read failed");
    }
    bytes += received;
    size -= static_cast<std::size_t>(received);
  }
}

void write_exact(int fd, const void *data, std::size_t size) {
  const auto *bytes = static_cast<const std::uint8_t *>(data);
  while (size > 0) {
    const ssize_t sent = send(fd, bytes, size, MSG_NOSIGNAL);
    if (sent <= 0) {
      throw std::runtime_error("socket write failed");
    }
    bytes += sent;
    size -= static_cast<std::size_t>(sent);
  }
}

std::vector<std::uint8_t> read_frame(int fd) {
  std::uint32_t network_size = 0;
  read_exact(fd, &network_size, sizeof(network_size));
  const std::uint32_t payload_size = ntohl(network_size);
  if (payload_size > mvision::kMaxFrameBytes) {
    throw std::runtime_error("frame too large");
  }
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload_size);
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  read_exact(fd, frame.data() + sizeof(network_size), payload_size);
  return frame;
}

int create_server(const std::string &path) {
  std::filesystem::create_directories(std::filesystem::path(path).parent_path());
  unlink(path.c_str());
  const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (fd < 0) {
    throw std::runtime_error("failed to create socket");
  }
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  if (path.size() >= sizeof(address.sun_path)) {
    close(fd);
    throw std::runtime_error("socket path too long");
  }
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  if (bind(fd, reinterpret_cast<const sockaddr *>(&address), sizeof(address)) != 0 ||
      listen(fd, 16) != 0) {
    close(fd);
    throw std::runtime_error("failed to bind socket");
  }
  chmod(path.c_str(), 0666);
  return fd;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc != 6) {
    return 2;
  }
  const std::string socket_path = argv[1];
  const auto slots = static_cast<std::uint32_t>(std::stoul(argv[2]));
  if (slots == 0 || cudaSetDevice(0) != cudaSuccess) {
    return 2;
  }
  mvision::PersistentJpegPipeline pipeline(0, slots, argv[3], argv[4], argv[5]);
  pipeline.start();
  const int server = create_server(socket_path);
  std::uint64_t next_token = 1;
  std::size_t completed_total = 0;

  for (;;) {
    const int client = accept4(server, nullptr, nullptr, SOCK_CLOEXEC);
    if (client < 0) {
      continue;
    }
    try {
      std::uint32_t network_count = 0;
      read_exact(client, &network_count, sizeof(network_count));
      const std::uint32_t count = ntohl(network_count);
      if (count == 0 || count > slots) {
        throw std::runtime_error("invalid microbatch size");
      }
      pipeline.begin_batch();
      std::unordered_map<std::uint64_t, std::string> request_ids;
      request_ids.reserve(count);
      for (std::uint32_t index = 0; index < count; ++index) {
        mvision::ImageRequest request = mvision::decode_request(read_frame(client));
        const std::uint64_t token = next_token++;
        request_ids.emplace(token, std::move(request.request_id));
        pipeline.push_jpeg(request.encoded_jpeg, token);
      }
      completed_total += count;
      if (!pipeline.wait_for_frames(completed_total, std::chrono::seconds(120))) {
        throw std::runtime_error("pipeline timeout");
      }
      auto results = pipeline.take_results();
      std::sort(results.begin(), results.end(), [](const auto &left, const auto &right) {
        return left.pts_token < right.pts_token;
      });
      for (const auto &result : results) {
        const auto request = request_ids.find(result.pts_token);
        if (request == request_ids.end()) {
          continue;
        }
        mvision::ImageResult response{request->second, "OK", "", {}};
        response.faces.reserve(result.faces.size());
        for (std::size_t ordinal = 0; ordinal < result.faces.size(); ++ordinal) {
          const auto &face = result.faces[ordinal];
          response.faces.push_back({static_cast<std::uint32_t>(ordinal), face.left, face.top,
                                    face.width, face.height, face.landmarks_xy, face.confidence,
                                    face.embedding, face.aligned_jpeg});
        }
        const auto frame = mvision::encode_result(response);
        write_exact(client, frame.data(), frame.size());
      }
    } catch (const std::exception &) {
    }
    close(client);
  }
}
