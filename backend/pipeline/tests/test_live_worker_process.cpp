#include "mvision/live_protocol.hpp"
#include "mvision/live_worker_queue.hpp"

#include <arpa/inet.h>
#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#include <array>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iterator>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <variant>
#include <vector>

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
constexpr const char* kFaceId = "019b0000-0000-7000-8000-000000000003";
constexpr const char* kTraceparent =
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

mvision::ProtocolHeader header(std::string type, std::uint64_t sequence) {
  return {mvision::kLiveProtocolVersion, std::move(type), kCameraId, kRunId,
          1, sequence, kTraceparent, std::nullopt};
}

struct WorkerProcess {
  pid_t pid{-1};
  int input{-1};
  int output{-1};
  int errors{-1};
  std::thread error_reader;
  mutable std::mutex error_mutex;
  std::string captured_errors;

  WorkerProcess(const std::string& executable, const std::string& gpu_id) {
    int input_pipe[2]{};
    int output_pipe[2]{};
    int error_pipe[2]{};
    assert(pipe(input_pipe) == 0);
    assert(pipe(output_pipe) == 0);
    assert(pipe(error_pipe) == 0);
    pid = fork();
    assert(pid >= 0);
    if (pid == 0) {
      dup2(input_pipe[0], STDIN_FILENO);
      dup2(output_pipe[1], STDOUT_FILENO);
      dup2(error_pipe[1], STDERR_FILENO);
      close(input_pipe[0]);
      close(input_pipe[1]);
      close(output_pipe[0]);
      close(output_pipe[1]);
      close(error_pipe[0]);
      close(error_pipe[1]);
      execl(executable.c_str(), executable.c_str(), gpu_id.c_str(), nullptr);
      _exit(127);
    }
    close(input_pipe[0]);
    close(output_pipe[1]);
    close(error_pipe[1]);
    input = input_pipe[1];
    output = output_pipe[0];
    errors = error_pipe[0];
    error_reader = std::thread([this] {
      std::array<char, 4096> buffer{};
      while (true) {
        const auto count = read(errors, buffer.data(), buffer.size());
        if (count <= 0) break;
        std::lock_guard lock(error_mutex);
        captured_errors.append(buffer.data(), static_cast<std::size_t>(count));
      }
    });
    bool exec_complete = false;
    for (int attempt = 0; attempt < 100; ++attempt) {
      std::ifstream stream("/proc/" + std::to_string(pid) + "/cmdline");
      std::string executable_name;
      std::getline(stream, executable_name, '\0');
      if (executable_name == executable) {
        exec_complete = true;
        break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    assert(exec_complete);
  }

  ~WorkerProcess() {
    if (input >= 0) close(input);
    if (output >= 0) close(output);
    if (pid > 0) {
      kill(pid, SIGKILL);
      waitpid(pid, nullptr, 0);
    }
    if (error_reader.joinable()) error_reader.join();
    if (errors >= 0) close(errors);
  }

  void write_bytes(const std::vector<std::uint8_t>& bytes) const {
    std::size_t offset = 0;
    while (offset < bytes.size()) {
      const auto count = write(input, bytes.data() + offset, bytes.size() - offset);
      assert(count > 0);
      offset += static_cast<std::size_t>(count);
    }
  }

  void send(const mvision::LiveMessage& message) const {
    write_bytes(mvision::encode_live_message(message));
  }

  std::vector<std::uint8_t> read_frame(int timeout_ms = 20'000) const {
    pollfd descriptor{output, POLLIN, 0};
    if (poll(&descriptor, 1, timeout_ms) != 1) {
      throw std::runtime_error("worker event timeout: " + stderr_text());
    }
    std::uint32_t network_size = 0;
    read_exact(reinterpret_cast<std::uint8_t*>(&network_size), sizeof(network_size));
    const auto payload_size = ntohl(network_size);
    assert(payload_size > 0 && payload_size <= mvision::kMaxLiveFrameBytes);
    std::vector<std::uint8_t> frame(sizeof(network_size) + payload_size);
    std::memcpy(frame.data(), &network_size, sizeof(network_size));
    read_exact(frame.data() + sizeof(network_size), payload_size);
    return frame;
  }

  bool has_output(int timeout_ms) const {
    pollfd descriptor{output, POLLIN, 0};
    return poll(&descriptor, 1, timeout_ms) == 1 &&
           (descriptor.revents & POLLIN) != 0;
  }

  void close_output() {
    close(output);
    output = -1;
  }

  void close_input() {
    close(input);
    input = -1;
  }

  int wait(int timeout_ms = 20'000) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(timeout_ms);
    int status = 0;
    while (std::chrono::steady_clock::now() < deadline) {
      const auto result = waitpid(pid, &status, WNOHANG);
      if (result == pid) {
        pid = -1;
        if (error_reader.joinable()) error_reader.join();
        return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    throw std::runtime_error("worker exit timeout");
  }

  std::string command_line() const {
    std::ifstream stream("/proc/" + std::to_string(pid) + "/cmdline");
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
  }

  std::string stderr_text() const {
    std::lock_guard lock(error_mutex);
    return captured_errors;
  }

 private:
  void read_exact(std::uint8_t* bytes, std::size_t size) const {
    std::size_t offset = 0;
    while (offset < size) {
      const auto count = read(output, bytes + offset, size - offset);
      if (count <= 0) {
        throw std::runtime_error("worker protocol closed: " + stderr_text());
      }
      offset += static_cast<std::size_t>(count);
    }
  }
};

mvision::StartCommand start_command(int gpu_id, const std::string& uri,
                                    char** argv) {
  return {header("start", 1), uri, static_cast<std::uint32_t>(gpu_id),
          argv[3], argv[5], argv[6], argv[4], "/live/test", 5400, 8554, 200, 2,
          -1, 2'000'000'000};
}

void expect_state(WorkerProcess& worker, const std::string& expected) {
  const auto event = mvision::decode_live_message(worker.read_frame());
  assert(std::holds_alternative<mvision::StateEvent>(event));
  assert(std::get<mvision::StateEvent>(event).state == expected);
}

void test_queue_saturation_is_bounded() {
  mvision::LiveWorkerEventQueue queue;
  for (std::uint64_t index = 0; index < 10'000; ++index) {
    queue.push(mvision::TrackEvidenceEvent{
        header("track_evidence", index), index % 1'000, index + 1, 1, 2, {}, {}});
  }
  for (std::uint64_t index = 0; index < 100; ++index) {
    queue.push(mvision::NativeOperationEvent{
        header("native_operation", index), "inference_window", index, index + 1,
        "ok", std::nullopt, {}});
    queue.push(mvision::MetricsEvent{header("metrics", index), {{"sample", index}}, {}});
  }
  for (std::uint64_t index = 0; index < 32; ++index) {
    assert(queue.push(mvision::StateEvent{header("state", index), "ACTIVE",
                                          std::nullopt}));
  }
  assert(!queue.push(mvision::StateEvent{header("state", 33), "ACTIVE",
                                         std::nullopt}));
  const auto stats = queue.stats();
  assert(stats.control == 32);
  assert(stats.evidence == 256);
  assert(stats.metrics == 1);
  assert(stats.operations == 64);
  assert(stats.dropped > 0);
  assert(std::holds_alternative<mvision::StateEvent>(*queue.pop()));
  queue.close();

  mvision::LiveAssignmentQueue assignments;
  std::array<float, 512> reference{};
  reference[0] = 1.0F;
  for (std::uint64_t index = 0; index < 10'000; ++index) {
    assignments.push(mvision::IdentityAssignment{
        header("identity_assignment", index), index % 300, index / 300 + 1,
        1, "known", std::string("Test"), std::string(kFaceId), 0.9F, 0.8F,
        reference, index});
  }
  assert(assignments.size() == 256);
  assert(assignments.pop().has_value());
}

void test_idle_and_signal(const std::string& executable) {
  WorkerProcess worker(executable, "0");
  assert(!worker.has_output(250));
  assert(kill(worker.pid, SIGTERM) == 0);
  assert(worker.wait() == 0);
}

void test_malformed_frame(const std::string& executable) {
  WorkerProcess worker(executable, "0");
  worker.write_bytes({0, 0, 0, 1, 0xC1});
  const auto event = mvision::decode_live_message(worker.read_frame());
  assert(std::holds_alternative<mvision::FailedEvent>(event));
  assert(std::get<mvision::FailedEvent>(event).error_code == "LIVE_PROTOCOL_ERROR");
  assert(worker.wait() != 0);
}

void test_truncated_frame(const std::string& executable) {
  WorkerProcess worker(executable, "0");
  worker.write_bytes({0, 0, 0, 8, 0x81, 0xA1, 0x78});
  worker.close_input();
  const auto event = mvision::decode_live_message(worker.read_frame());
  assert(std::holds_alternative<mvision::FailedEvent>(event));
  assert(std::get<mvision::FailedEvent>(event).error_code == "LIVE_PROTOCOL_ERROR");
  assert(worker.wait() != 0);
}

void test_start_assignment_stop(char** argv) {
  const std::string uri = argv[2];
  WorkerProcess worker(argv[1], "0");
  assert(worker.command_line().find(uri) == std::string::npos);
  worker.send(start_command(0, uri, argv));
  auto event = mvision::decode_live_message(worker.read_frame());
  assert(std::holds_alternative<mvision::HelloEvent>(event));
  expect_state(worker, "STARTING");

  std::array<float, 512> assignment_reference{};
  assignment_reference[0] = 1.0F;
  mvision::IdentityAssignment assignment{
      header("identity_assignment", 2), 42, 1, 1, "known", std::string("Test"),
      std::string(kFaceId), 0.9F, 0.8F, assignment_reference, 1};
  worker.send(assignment);
  worker.send(assignment);
  worker.send(mvision::StopCommand{header("stop", 3), "operator",
                                   5'000'000'000});

  bool saw_stopping = false;
  bool saw_stopped = false;
  bool saw_stale_assignment = false;
  while (!saw_stopped) {
    event = mvision::decode_live_message(worker.read_frame());
    if (const auto* state = std::get_if<mvision::StateEvent>(&event)) {
      saw_stopping = saw_stopping || state->state == "STOPPING";
      saw_stopped = saw_stopped || state->state == "STOPPED";
    }
    if (const auto* metrics = std::get_if<mvision::MetricsEvent>(&event)) {
      const auto found = metrics->counters.find("rejected_commands");
      saw_stale_assignment = saw_stale_assignment ||
                             (found != metrics->counters.end() && found->second == 1);
    }
    if (std::holds_alternative<mvision::StoppedEvent>(event)) saw_stopped = true;
  }
  assert(saw_stopping);
  assert(saw_stale_assignment);
  assert(worker.wait() == 0);
  assert(worker.stderr_text().find(uri) == std::string::npos);
}

void test_sigterm_uses_close_path(char** argv) {
  WorkerProcess worker(argv[1], "0");
  worker.send(start_command(0, argv[2], argv));
  static_cast<void>(mvision::decode_live_message(worker.read_frame()));
  expect_state(worker, "STARTING");
  assert(kill(worker.pid, SIGTERM) == 0);
  bool saw_stopping = false;
  bool saw_stopped = false;
  while (!saw_stopped) {
    const auto event = mvision::decode_live_message(worker.read_frame());
    if (const auto* state = std::get_if<mvision::StateEvent>(&event)) {
      saw_stopping = saw_stopping || state->state == "STOPPING";
    }
    saw_stopped = std::holds_alternative<mvision::StoppedEvent>(event);
  }
  assert(saw_stopping);
  assert(worker.wait() == 0);
}

void test_broken_stdout_is_controlled(char** argv) {
  WorkerProcess worker(argv[1], "0");
  worker.send(start_command(0, argv[2], argv));
  static_cast<void>(mvision::decode_live_message(worker.read_frame()));
  expect_state(worker, "STARTING");
  worker.close_output();
  worker.send(mvision::StopCommand{header("stop", 3), "operator",
                                   5'000'000'000});
  const int exit_code = worker.wait();
  assert(exit_code != 0);
  assert(exit_code != 128 + SIGPIPE);
}

}  // namespace

int main(int argc, char** argv) {
  std::array<std::string, 7> defaults;
  std::array<char*, 7> default_argv{};
  if (argc == 1) {
    const auto workspace = std::filesystem::current_path();
    defaults = {argv[0],
                (workspace / "build/pipeline/mvision_live_worker").string(),
                "rtsp://rtsp-fixture:8555/friends",
                (workspace / "configs/video_pgie_yolov8_face.txt").string(),
                (workspace / "configs/video_tracker_nvdcf.yml").string(),
                (workspace / "configs/video_preprocess_arcface.txt").string(),
                (workspace / "configs/video_sgie_arcface_r50.txt").string()};
    for (std::size_t index = 0; index < defaults.size(); ++index) {
      default_argv[index] = defaults[index].data();
    }
    argc = static_cast<int>(default_argv.size());
    argv = default_argv.data();
  }
  assert(argc == 7);
  test_queue_saturation_is_bounded();
  test_idle_and_signal(argv[1]);
  test_malformed_frame(argv[1]);
  test_truncated_frame(argv[1]);
  test_start_assignment_stop(argv);
  test_sigterm_uses_close_path(argv);
  test_broken_stdout_is_controlled(argv);
  return 0;
}
