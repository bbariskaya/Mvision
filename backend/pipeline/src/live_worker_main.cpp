#include "mvision/live_pipeline.hpp"
#include "mvision/live_protocol.hpp"
#include "mvision/live_worker_queue.hpp"

#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

namespace {

std::atomic_bool signal_requested{false};

void handle_signal(int) { signal_requested.store(true); }

mvision::ProtocolHeader fallback_header(std::string type, std::uint64_t sequence) {
  return {mvision::kLiveProtocolVersion,
          std::move(type),
          "00000000-0000-0000-0000-000000000001",
          "00000000-0000-0000-0000-000000000001",
          "00000000-0000-0000-0000-000000000002",
          1,
          1,
          sequence,
          "00-00000000000000000000000000000001-0000000000000001-00",
          std::nullopt};
}

void write_exact(int fd, const std::uint8_t* bytes, std::size_t size,
                 const std::atomic_bool& stop) {
  std::size_t offset = 0;
  while (offset < size) {
    const auto count = write(fd, bytes + offset, size - offset);
    if (count > 0) {
      offset += static_cast<std::size_t>(count);
      continue;
    }
    if (count < 0 && errno == EINTR) continue;
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      pollfd descriptor{fd, POLLOUT, 0};
      poll(&descriptor, 1, 100);
      if (stop.load()) throw std::runtime_error("LIVE_WRITER_STOPPED");
      continue;
    }
    throw std::runtime_error("LIVE_WRITER_BROKEN_PIPE");
  }
}

std::optional<std::vector<std::uint8_t>> read_frame(int fd) {
  pollfd descriptor{fd, POLLIN, 0};
  const auto ready = poll(&descriptor, 1, 100);
  if (ready == 0) return std::nullopt;
  if (ready < 0 && errno == EINTR) return std::nullopt;
  if (ready < 0) throw std::runtime_error("LIVE_PROTOCOL_READ_ERROR");
  if ((descriptor.revents & (POLLHUP | POLLERR)) != 0 &&
      (descriptor.revents & POLLIN) == 0) {
    return std::vector<std::uint8_t>{};
  }
  std::uint32_t network_size = 0;
  std::size_t offset = 0;
  while (offset < sizeof(network_size)) {
    const auto count = read(fd, reinterpret_cast<std::uint8_t*>(&network_size) + offset,
                            sizeof(network_size) - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) throw std::runtime_error("TRUNCATED_FRAME");
    offset += static_cast<std::size_t>(count);
  }
  const auto payload_size = ntohl(network_size);
  if (payload_size == 0 || payload_size > mvision::kMaxLiveFrameBytes) {
    throw std::runtime_error("FRAME_TOO_LARGE");
  }
  std::vector<std::uint8_t> frame(sizeof(network_size) + payload_size);
  std::memcpy(frame.data(), &network_size, sizeof(network_size));
  offset = sizeof(network_size);
  while (offset < frame.size()) {
    const auto count = read(fd, frame.data() + offset, frame.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) throw std::runtime_error("TRUNCATED_FRAME");
    offset += static_cast<std::size_t>(count);
  }
  return frame;
}

std::string state_name(mvision::LiveRuntimeState state) {
  switch (state) {
    case mvision::LiveRuntimeState::Starting: return "STARTING";
    case mvision::LiveRuntimeState::Active: return "ACTIVE";
    case mvision::LiveRuntimeState::Reconnecting: return "RECONNECTING";
    case mvision::LiveRuntimeState::Stopping: return "STOPPING";
    case mvision::LiveRuntimeState::Stopped: return "STOPPED";
    case mvision::LiveRuntimeState::Failed: return "FAILED";
  }
  return "FAILED";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fprintf(stderr, "LIVE_WORKER_USAGE_ERROR\n");
    return 2;
  }
  signal(SIGPIPE, SIG_IGN);
  signal(SIGTERM, handle_signal);
  signal(SIGINT, handle_signal);
  int protocol_fd = -1;
  try {
    const int gpu_id = std::stoi(argv[1]);
    std::fflush(stdout);
    protocol_fd = dup(STDOUT_FILENO);
    if (protocol_fd < 0 || dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
      throw std::runtime_error("LIVE_PROTOCOL_OUTPUT_ERROR");
    }
    const int flags = fcntl(protocol_fd, F_GETFL, 0);
    fcntl(protocol_fd, F_SETFL, flags | O_NONBLOCK);

    mvision::LiveWorkerEventQueue events;
    mvision::LiveAssignmentQueue assignments;
    std::atomic_bool writer_stop{false};
    std::atomic_bool writer_failed{false};
    std::thread writer([&] {
      try {
        std::uint64_t output_sequence = 100;
        while (const auto event = events.pop()) {
          auto outbound = *event;
          std::visit(
              [&](auto& value) { value.header.sequence = output_sequence++; },
              outbound);
          const auto frame = mvision::encode_live_message(outbound);
          write_exact(protocol_fd, frame.data(), frame.size(), writer_stop);
        }
      } catch (...) {
        std::fprintf(stderr, "LIVE_WRITER_FAILED\n");
        writer_failed.store(true);
        signal_requested.store(true);
      }
    });

    std::optional<mvision::StartCommand> start;
    std::optional<mvision::DecodeContext> context;
    std::unique_ptr<mvision::LivePipeline> pipeline;
    std::atomic_uint64_t sequence{100};
    bool clean_stop = false;
    bool fatal_protocol_error = false;

    auto event_header = [&](std::string type) {
      auto value = start.has_value() ? start->header : fallback_header(type, 0);
      value.message_type = std::move(type);
      value.sequence = sequence.fetch_add(1);
      return value;
    };
    auto stop_pipeline = [&] {
      if (pipeline != nullptr) {
        pipeline->stop(mvision::StopReason::Requested);
        pipeline->close();
      }
    };

    while (!clean_stop && !writer_failed.load()) {
      if (signal_requested.load()) {
        stop_pipeline();
        clean_stop = true;
        break;
      }
      std::optional<std::vector<std::uint8_t>> frame;
      try {
        frame = read_frame(STDIN_FILENO);
      } catch (const std::exception&) {
        events.push(mvision::FailedEvent{
            fallback_header("failed", 1), "LIVE_PROTOCOL_ERROR",
            "live worker protocol failed"});
        fatal_protocol_error = true;
        break;
      }
      if (!frame.has_value()) continue;
      if (frame->empty()) {
        if (pipeline != nullptr) stop_pipeline();
        clean_stop = pipeline == nullptr;
        break;
      }
      try {
        auto message = mvision::decode_live_message(*frame,
                                                    context.has_value() ? &*context : nullptr);
        if (const auto* command = std::get_if<mvision::StartCommand>(&message)) {
          if (start.has_value() || static_cast<int>(command->gpu_id) != gpu_id) {
            throw mvision::LiveProtocolError("INVALID_START");
          }
          start = *command;
          context = mvision::DecodeContext{command->header.session_id,
                                           command->header.camera_id,
                                           command->header.run_id,
                                           command->header.generation,
                                           command->header.runtime_attempt, {}};
          events.push(mvision::HelloEvent{event_header("hello"), "mvision-live-worker",
                                          "1.24.2", "9.0.0"});
          mvision::LivePipelineCallbacks callbacks;
          callbacks.on_state = [&](mvision::LiveRuntimeState state) {
            events.push(mvision::StateEvent{event_header("state"), state_name(state),
                                            std::nullopt});
          };
          callbacks.on_evidence = [&](const mvision::TrackEvidenceEvent& event) {
            auto outbound = event;
            outbound.header = event_header("track_evidence");
            events.push(std::move(outbound));
          };
          callbacks.on_metrics = [&](const mvision::LivePipelineCounters& counters) {
            events.push(mvision::MetricsEvent{
                event_header("metrics"),
                {{"decoded_frames", counters.decoded_frames},
                 {"tracked_objects", counters.tracked_objects},
                 {"eligible_objects", counters.eligible_object_count},
                 {"embedding_count", counters.embedding_count},
                 {"missing_embeddings", counters.missing_embedding_count},
                 {"embedding_cosine_samples", counters.embedding_cosine_samples},
                 {"dropped_events", events.dropped_events()}}, {}});
          };
          callbacks.on_native_operation = [&](const mvision::NativeOperationEvent& event) {
            auto outbound = event;
            outbound.header = event_header("native_operation");
            events.push(std::move(outbound));
          };
          callbacks.on_failure = [&](const mvision::FailedEvent& event) {
            auto outbound = event;
            outbound.header = event_header("failed");
            events.push(std::move(outbound));
          };
          callbacks.on_stopped = [&](const mvision::StoppedEvent& stopped) {
            auto event = stopped;
            event.header = event_header("stopped");
            event.dropped_events = events.dropped_events();
            events.push(event);
          };
          pipeline = std::make_unique<mvision::LivePipeline>(std::move(callbacks));
          mvision::LivePipelineOptions options;
          options.uri = command->uri;
          options.gpu_id = gpu_id;
          options.pgie_config_path = command->pgie_config_path;
          options.tracker_config_path = command->tracker_config_path;
          options.preprocess_config_path = command->preprocess_config_path;
          options.sgie_config_path = command->sgie_config_path;
          options.sample_every_n = command->sample_every_n;
          options.latency_ms = command->latency_ms;
          options.reconnect_interval_seconds = command->reconnect_interval_seconds;
          options.reconnect_attempts = command->reconnect_attempts;
          options.frame_timeout_ns = command->frame_timeout_ns;
          options.output_mount_path = command->output_mount_path;
          options.output_udp_port = command->output_udp_port;
          options.output_rtsp_port = command->output_rtsp_port;
          options.event_header = command->header;
          pipeline->start(options);
        } else if (const auto* assignment =
                       std::get_if<mvision::IdentityAssignment>(&message)) {
          const bool queued = assignments.push(*assignment);
          const auto pending = assignments.pop();
          if (!queued || !pending.has_value() || pipeline == nullptr ||
              !pipeline->apply_assignment(*pending)) {
            events.push(mvision::MetricsEvent{
                event_header("metrics"), {{"stale_assignments", 1}}, {}});
          }
        } else if (std::holds_alternative<mvision::StopCommand>(message)) {
          stop_pipeline();
          clean_stop = true;
        } else {
          throw mvision::LiveProtocolError("UNEXPECTED_MESSAGE");
        }
      } catch (const mvision::LiveProtocolError&) {
        if (!start.has_value()) {
          events.push(mvision::FailedEvent{
              fallback_header("failed", 1), "LIVE_PROTOCOL_ERROR",
              "live worker protocol failed"});
          fatal_protocol_error = true;
          break;
        }
        events.push(mvision::MetricsEvent{
            event_header("metrics"), {{"rejected_commands", 1}}, {}});
      }
    }

    events.close();
    writer.join();
    writer_stop.store(true);
    close(protocol_fd);
    return clean_stop && !fatal_protocol_error && !writer_failed.load() ? 0 : 1;
  } catch (...) {
    if (protocol_fd >= 0) {
      try {
        const auto frame = mvision::encode_live_message(mvision::FailedEvent{
            fallback_header("failed", 1), "LIVE_PROTOCOL_ERROR",
            "live worker protocol failed"});
        std::atomic_bool never_stop{false};
        write_exact(protocol_fd, frame.data(), frame.size(), never_stop);
      } catch (...) {
      }
      close(protocol_fd);
    }
    std::fprintf(stderr, "LIVE_WORKER_FAILED\n");
    return 1;
  }
}
