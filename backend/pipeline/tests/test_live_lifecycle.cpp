#include "mvision/live_pipeline.hpp"

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                        \
  do {                                                                           \
    if (!(condition)) throw std::runtime_error("assertion failed: " #condition); \
  } while (false)
#endif

namespace {

struct Recorder {
  std::uint64_t now{};
  std::vector<mvision::LiveRuntimeState> states;
  std::vector<std::pair<std::string, std::string>> failures;

  mvision::LiveLifecycle make(std::uint32_t rebuild_attempts = 1) {
    return mvision::LiveLifecycle(
        {100, 200, rebuild_attempts}, [this] { return now; },
        [this](mvision::LiveRuntimeState state) { states.push_back(state); },
        [this](std::string code, std::string message) {
          failures.emplace_back(std::move(code), std::move(message));
        });
  }
};

void expect_states(const Recorder& recorder,
                   std::vector<mvision::LiveRuntimeState> expected) {
  assert(recorder.states == expected);
}

void test_first_frame_and_recovery() {
  Recorder recorder;
  auto lifecycle = recorder.make();
  lifecycle.start();
  recorder.now = 10;
  lifecycle.on_frame();
  expect_states(recorder, {mvision::LiveRuntimeState::Starting,
                           mvision::LiveRuntimeState::Active});

  recorder.now = 111;
  lifecycle.poll();
  assert(lifecycle.state() == mvision::LiveRuntimeState::Reconnecting);
  recorder.now = 112;
  lifecycle.on_frame();
  expect_states(recorder, {mvision::LiveRuntimeState::Starting,
                           mvision::LiveRuntimeState::Active,
                           mvision::LiveRuntimeState::Reconnecting,
                           mvision::LiveRuntimeState::Active});
  assert(recorder.failures.empty());
}

void test_rebuild_budget_exhaustion() {
  Recorder recorder;
  auto lifecycle = recorder.make(1);
  lifecycle.start();
  lifecycle.on_frame();
  recorder.now = 101;
  lifecycle.poll();
  recorder.now = 302;
  assert(lifecycle.poll() == mvision::LifecycleAction::RebuildGraph);
  lifecycle.on_graph_rebuild_result(false);
  assert(lifecycle.state() == mvision::LiveRuntimeState::Failed);
  assert(recorder.failures.size() == 1);
  assert(recorder.failures[0].first == "LIVE_PIPELINE_ERROR");
  assert(recorder.failures[0].second == "live pipeline recovery exhausted");
}

void test_startup_without_first_frame_reconnects() {
  Recorder recorder;
  auto lifecycle = recorder.make();
  lifecycle.start();
  recorder.now = 101;
  lifecycle.poll();
  expect_states(recorder, {mvision::LiveRuntimeState::Starting,
                           mvision::LiveRuntimeState::Reconnecting});
}

void expect_stop_from(mvision::LiveRuntimeState target) {
  Recorder recorder;
  auto lifecycle = recorder.make();
  lifecycle.start();
  if (target == mvision::LiveRuntimeState::Active ||
      target == mvision::LiveRuntimeState::Reconnecting) {
    lifecycle.on_frame();
  }
  if (target == mvision::LiveRuntimeState::Reconnecting) {
    recorder.now = 101;
    lifecycle.poll();
  }
  assert(lifecycle.state() == target);
  lifecycle.stop();
  assert(lifecycle.state() == mvision::LiveRuntimeState::Stopping);
  lifecycle.close();
  lifecycle.stop();
  lifecycle.close();
  assert(lifecycle.state() == mvision::LiveRuntimeState::Stopped);
  assert(recorder.states[recorder.states.size() - 2] ==
         mvision::LiveRuntimeState::Stopping);
  assert(recorder.states.back() == mvision::LiveRuntimeState::Stopped);
  assert(static_cast<std::size_t>(std::count(
             recorder.states.begin(), recorder.states.end(),
             mvision::LiveRuntimeState::Stopped)) == 1);
}

void test_stop_is_idempotent_from_non_terminal_states() {
  expect_stop_from(mvision::LiveRuntimeState::Starting);
  expect_stop_from(mvision::LiveRuntimeState::Active);
  expect_stop_from(mvision::LiveRuntimeState::Reconnecting);
}

void test_invalid_transition_is_sanitized_once() {
  Recorder recorder;
  auto lifecycle = recorder.make();
  lifecycle.on_frame();
  lifecycle.on_frame();
  assert(lifecycle.state() == mvision::LiveRuntimeState::Failed);
  assert(recorder.failures.size() == 1);
  assert(recorder.failures[0].first == "LIVE_PIPELINE_STATE_ERROR");
  assert(recorder.failures[0].second == "invalid live pipeline transition");
  assert(recorder.failures[0].second.find("rtsp") == std::string::npos);
}

}  // namespace

int main() {
  test_first_frame_and_recovery();
  test_rebuild_budget_exhaustion();
  test_startup_without_first_frame_reconnects();
  test_stop_is_idempotent_from_non_terminal_states();
  test_invalid_transition_is_sanitized_once();
  return 0;
}
