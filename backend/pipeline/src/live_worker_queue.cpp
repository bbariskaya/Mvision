#include "mvision/live_worker_queue.hpp"

#include <utility>

namespace mvision {

bool LiveWorkerEventQueue::push(LiveMessage event) {
  std::lock_guard lock(mutex_);
  if (closed_) return false;
  if (const auto* evidence = std::get_if<TrackEvidenceEvent>(&event)) {
    const auto found = evidence_.find(evidence->tracker_id);
    if (found != evidence_.end()) {
      if (evidence->evidence_revision >
          std::get<TrackEvidenceEvent>(found->second).evidence_revision) {
        found->second = std::move(event);
      }
    } else if (evidence_.size() < 256) {
      evidence_order_.push_back(evidence->tracker_id);
      evidence_.emplace(evidence->tracker_id, std::move(event));
    } else {
      ++dropped_events_;
    }
  } else if (std::holds_alternative<MetricsEvent>(event)) {
    metrics_ = std::move(event);
  } else if (std::holds_alternative<NativeOperationEvent>(event)) {
    if (operations_.size() == 64) {
      operations_.pop_front();
      ++dropped_events_;
    }
    operations_.push_back(std::move(event));
  } else {
    if (control_.size() == 32) return false;
    control_.push_back(std::move(event));
  }
  changed_.notify_one();
  return true;
}

std::optional<LiveMessage> LiveWorkerEventQueue::pop() {
  std::unique_lock lock(mutex_);
  changed_.wait(lock, [this] { return closed_ || !empty(); });
  if (!control_.empty()) {
    auto event = std::move(control_.front());
    control_.pop_front();
    return event;
  }
  if (!evidence_order_.empty()) {
    const auto tracker_id = evidence_order_.front();
    evidence_order_.pop_front();
    auto found = evidence_.find(tracker_id);
    auto event = std::move(found->second);
    evidence_.erase(found);
    return event;
  }
  if (metrics_.has_value()) {
    auto event = std::move(metrics_);
    metrics_.reset();
    return event;
  }
  if (!operations_.empty()) {
    auto event = std::move(operations_.front());
    operations_.pop_front();
    return event;
  }
  return std::nullopt;
}

void LiveWorkerEventQueue::close() {
  std::lock_guard lock(mutex_);
  closed_ = true;
  changed_.notify_all();
}

std::uint64_t LiveWorkerEventQueue::dropped_events() const {
  std::lock_guard lock(mutex_);
  return dropped_events_;
}

LiveWorkerQueueStats LiveWorkerEventQueue::stats() const {
  std::lock_guard lock(mutex_);
  return {control_.size(), evidence_.size(), metrics_.has_value() ? 1U : 0U,
          operations_.size(), dropped_events_};
}

bool LiveWorkerEventQueue::empty() const {
  return control_.empty() && evidence_.empty() && !metrics_.has_value() &&
         operations_.empty();
}

bool LiveAssignmentQueue::push(IdentityAssignment assignment) {
  std::lock_guard lock(mutex_);
  const auto found = assignments_.find(assignment.tracker_id);
  if (found != assignments_.end()) {
    if (assignment.assignment_revision <= found->second.assignment_revision) return false;
    found->second = std::move(assignment);
    return true;
  }
  if (assignments_.size() == 256) return false;
  order_.push_back(assignment.tracker_id);
  assignments_.emplace(assignment.tracker_id, std::move(assignment));
  return true;
}

std::optional<IdentityAssignment> LiveAssignmentQueue::pop() {
  std::lock_guard lock(mutex_);
  if (order_.empty()) return std::nullopt;
  const auto tracker_id = order_.front();
  order_.pop_front();
  auto found = assignments_.find(tracker_id);
  auto assignment = std::move(found->second);
  assignments_.erase(found);
  return assignment;
}

std::size_t LiveAssignmentQueue::size() const {
  std::lock_guard lock(mutex_);
  return assignments_.size();
}

}  // namespace mvision
