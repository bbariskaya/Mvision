#pragma once

#include "mvision/live_protocol.hpp"

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <optional>
#include <unordered_map>

namespace mvision {

struct LiveWorkerQueueStats {
  std::size_t control{};
  std::size_t evidence{};
  std::size_t metrics{};
  std::size_t operations{};
  std::uint64_t dropped{};
};

class LiveWorkerEventQueue {
 public:
  bool push(LiveMessage event);
  std::optional<LiveMessage> pop();
  void close();
  std::uint64_t dropped_events() const;
  LiveWorkerQueueStats stats() const;

 private:
  bool empty() const;

  mutable std::mutex mutex_;
  std::condition_variable changed_;
  std::deque<LiveMessage> control_;
  std::unordered_map<std::uint64_t, LiveMessage> evidence_;
  std::deque<std::uint64_t> evidence_order_;
  std::optional<LiveMessage> metrics_;
  std::deque<LiveMessage> operations_;
  std::uint64_t dropped_events_{};
  bool closed_{};
};

class LiveAssignmentQueue {
 public:
  bool push(IdentityAssignment assignment);
  std::optional<IdentityAssignment> pop();
  std::size_t size() const;

 private:
  mutable std::mutex mutex_;
  std::unordered_map<std::uint64_t, IdentityAssignment> assignments_;
  std::deque<std::uint64_t> order_;
};

}  // namespace mvision
