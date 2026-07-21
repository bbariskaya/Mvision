#include "mvision/live_pipeline.hpp"

#include "mvision/aligned_evidence_meta.hpp"
#include "mvision/video_pipeline.hpp"

#include <gst/gst.h>
#include <gstnvdsinfer.h>
#include <gstnvdsmeta.h>
#include <nvdspreprocess_meta.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mvision {
namespace {

using Clock = std::chrono::steady_clock;

std::uint64_t monotonic_ns() {
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          Clock::now().time_since_epoch())
          .count());
}

GstElement* make_element(const char* factory, const char* name) {
  GstElement* element = gst_element_factory_make(factory, name);
  if (element == nullptr) {
    throw std::runtime_error(std::string("missing GStreamer element: ") + factory);
  }
  return element;
}

void require_link(bool linked, const char* description) {
  if (!linked) {
    throw std::runtime_error(std::string("failed to link ") + description);
  }
}

float clamp_value(float value, float minimum, float maximum) {
  return std::max(minimum, std::min(maximum, value));
}

std::vector<std::byte> copy_aligned_jpeg(const NvDsObjectMeta& object) {
  for (NvDsMetaList* item = object.obj_user_meta_list; item != nullptr;
       item = item->next) {
    const auto* user_meta = static_cast<const NvDsUserMeta*>(item->data);
    if (user_meta != nullptr &&
        user_meta->base_meta.meta_type == aligned_jpeg_meta_type() &&
        user_meta->user_meta_data != nullptr) {
      const auto& bytes =
          static_cast<const AlignedJpegMeta*>(user_meta->user_meta_data)->bytes;
      std::vector<std::byte> copy;
      copy.reserve(bytes.size());
      for (const std::uint8_t byte : bytes) {
        copy.push_back(static_cast<std::byte>(byte));
      }
      return copy;
    }
  }
  return {};
}

const char* stop_reason_name(StopReason reason) {
  switch (reason) {
    case StopReason::SmokeComplete:
      return "smoke_complete";
    case StopReason::Requested:
      return "requested";
    case StopReason::Failure:
      return "failure";
  }
  return "failure";
}

template <typename Callback, typename Value>
void notify(const Callback& callback, const Value& value) noexcept {
  if (!callback) return;
  try {
    callback(value);
  } catch (...) {
  }
}

struct TrackRuntime {
  TrackRuntime() : evidence(10, 250'000'000) {}

  TrackEvidenceBank evidence;
  IdentityAssignmentState identity;
  std::uint64_t revision{};
  std::uint64_t first_seen_ns{};
  std::uint64_t last_seen_ns{};
};

struct TrackedBox {
  std::uint64_t tracker_id{};
  float left{};
  float top{};
  float width{};
  float height{};
};

float intersection_over_union(const TrackedBox& left, const TrackedBox& right) {
  const float overlap_left = std::max(left.left, right.left);
  const float overlap_top = std::max(left.top, right.top);
  const float overlap_right =
      std::min(left.left + left.width, right.left + right.width);
  const float overlap_bottom =
      std::min(left.top + left.height, right.top + right.height);
  const float overlap_width = std::max(0.0F, overlap_right - overlap_left);
  const float overlap_height = std::max(0.0F, overlap_bottom - overlap_top);
  const float intersection = overlap_width * overlap_height;
  const float area = left.width * left.height + right.width * right.height -
                     intersection;
  return area > 0.0F ? intersection / area : 0.0F;
}

}  // namespace

class LivePipeline::Impl {
 public:
  explicit Impl(LivePipelineCallbacks selected_callbacks)
      : callbacks(std::move(selected_callbacks)) {
    static std::once_flag gst_init_flag;
    std::call_once(gst_init_flag, [] { gst_init(nullptr, nullptr); });
  }

  ~Impl() { close(); }

  void start(const LivePipelineOptions& selected_options) {
    if (started.load()) throw std::logic_error("live pipeline already started");
    if (selected_options.uri.empty() || selected_options.pgie_config_path.empty() ||
        selected_options.tracker_config_path.empty() ||
        selected_options.preprocess_config_path.empty() ||
        selected_options.sgie_config_path.empty() ||
        selected_options.batch_size != 1 || !selected_options.live_source ||
        selected_options.width == 0 || selected_options.height == 0 ||
        selected_options.sample_every_n == 0 || selected_options.gpu_id < 0) {
      throw std::invalid_argument("invalid live pipeline options");
    }
    options = selected_options;
    next_sequence.store(options.event_header.sequence);
    source_connect_started_ns = monotonic_ns();
    build();
    loop = g_main_loop_new(nullptr, FALSE);
    if (loop == nullptr) {
      close_graph();
      throw std::runtime_error("failed to create live pipeline loop");
    }
    started.store(true);
    notify(callbacks.on_state, LiveRuntimeState::Starting);
    worker = std::thread([this] { run(); });
  }

  bool apply_assignment(const IdentityAssignment& assignment) {
    std::lock_guard lock(track_mutex);
    return tracks.try_emplace(assignment.tracker_id).first->second.identity.apply(
        assignment);
  }

  void stop(StopReason selected_reason) {
    if (!started.load() || stop_requested.exchange(true)) return;
    stop_reason = selected_reason;
    notify(callbacks.on_state, LiveRuntimeState::Stopping);
    GMainLoop* current_loop = loop;
    if (current_loop != nullptr) g_main_loop_quit(current_loop);
  }

  void close() {
    stop(StopReason::Requested);
    if (worker.joinable()) worker.join();
    close_graph();
    if (loop != nullptr) {
      g_main_loop_unref(loop);
      loop = nullptr;
    }
    started.store(false);
  }

 private:
  ProtocolHeader header(std::string message_type) {
    ProtocolHeader value = options.event_header;
    value.protocol_version = value.protocol_version == 0 ? kLiveProtocolVersion
                                                         : value.protocol_version;
    value.message_type = std::move(message_type);
    value.sequence = next_sequence.fetch_add(1);
    return value;
  }

  void emit_operation(std::string operation, std::uint64_t started_ns,
                      std::map<std::string, NativeAttribute> attributes = {}) {
    notify(callbacks.on_native_operation,
           NativeOperationEvent{header("native_operation"), std::move(operation),
                                started_ns, monotonic_ns(), "ok", std::nullopt,
                                std::move(attributes)});
  }

  void emit_failure() {
    if (failed.exchange(true)) return;
    pipeline_errors.fetch_add(1);
    notify(callbacks.on_state, LiveRuntimeState::Failed);
    notify(callbacks.on_failure,
           FailedEvent{header("failed"), "LIVE_PIPELINE_ERROR",
                       "live pipeline failed"});
  }

  void run() noexcept {
    GstBus* bus = gst_element_get_bus(pipeline);
    bus_watch_id = gst_bus_add_watch(bus, &Impl::on_bus, this);
    gst_object_unref(bus);
    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) ==
        GST_STATE_CHANGE_FAILURE) {
      emit_failure();
    } else if (!failed.load()) {
      g_main_loop_run(loop);
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    if (!failed.load()) {
      notify(callbacks.on_state, LiveRuntimeState::Stopped);
      notify(callbacks.on_stopped,
             StoppedEvent{header("stopped"), counters.decoded_frames,
                          counters.emitted_evidence, 0, true,
                          stop_reason_name(stop_reason)});
    }
  }

  void build() {
    pipeline = gst_pipeline_new("mvision-live-pipeline");
    if (pipeline == nullptr) throw std::runtime_error("failed to create live pipeline");
    try {
      source = make_element("nvurisrcbin", "live-source");
      source_queue = make_element("queue", "live-source-queue");
      converter = make_element("nvvideoconvert", "live-video-converter");
      caps_filter = make_element("capsfilter", "live-nvmm-filter");
      streammux = make_element("nvstreammux", "live-muxer");
      pgie = make_element("nvinfer", "live-face-pgie");
      tracker = make_element("nvtracker", "live-face-tracker");
      preprocess = make_element("nvdspreprocess", "live-face-preprocess");
      sgie = make_element("nvinfer", "live-face-sgie");
      sink = make_element("fakesink", "live-inference-sink");

      g_object_set(source, "uri", options.uri.c_str(), "gpu-id", options.gpu_id,
                   "latency", options.latency_ms, "disable-audio", TRUE, nullptr);
      g_signal_connect(source, "pad-added", G_CALLBACK(&Impl::on_source_pad), this);
      g_object_set(source_queue, "max-size-buffers", 8U, "max-size-bytes", 0U,
                   "max-size-time", static_cast<guint64>(0), "leaky", 2, nullptr);
      GstCaps* caps = gst_caps_from_string("video/x-raw(memory:NVMM),format=NV12");
      if (caps == nullptr) throw std::runtime_error("failed to create live NVMM caps");
      g_object_set(caps_filter, "caps", caps, nullptr);
      gst_caps_unref(caps);
      g_object_set(streammux, "gpu-id", options.gpu_id, "batch-size",
                   options.batch_size, "width", options.width, "height",
                   options.height, "live-source", TRUE, "batched-push-timeout",
                   40000, "enable-padding", TRUE, nullptr);
      g_object_set(pgie, "config-file-path", options.pgie_config_path.c_str(),
                   "interval", options.sample_every_n - 1, nullptr);
      g_object_set(tracker, "gpu-id", options.gpu_id, "tracker-width", 640U,
                   "tracker-height", 384U, "ll-lib-file",
                   "/opt/nvidia/deepstream/deepstream/lib/"
                   "libnvds_nvmultiobjecttracker.so",
                   "ll-config-file", options.tracker_config_path.c_str(), nullptr);
      g_object_set(preprocess, "config-file",
                   options.preprocess_config_path.c_str(), nullptr);
      g_object_set(sgie, "config-file-path", options.sgie_config_path.c_str(),
                   "input-tensor-meta", TRUE, "output-tensor-meta", TRUE,
                   "raw-output-generated-callback", &Impl::on_sgie_output,
                   "raw-output-generated-userdata", this, nullptr);
      g_object_set(sink, "sync", FALSE, "async", FALSE, "enable-last-sample",
                   FALSE, nullptr);

      gst_bin_add_many(GST_BIN(pipeline), source, source_queue, converter,
                       caps_filter, streammux, pgie, tracker, preprocess, sgie,
                       sink, nullptr);
      require_link(gst_element_link_many(source_queue, converter, caps_filter,
                                         nullptr),
                   "live source conversion chain");
      GstPad* source_pad = gst_element_get_static_pad(caps_filter, "src");
      mux_sink_pad = gst_element_request_pad_simple(streammux, "sink_0");
      if (source_pad == nullptr || mux_sink_pad == nullptr ||
          gst_pad_link(source_pad, mux_sink_pad) != GST_PAD_LINK_OK) {
        if (source_pad != nullptr) gst_object_unref(source_pad);
        throw std::runtime_error("failed to link live source to nvstreammux");
      }
      gst_object_unref(source_pad);
      require_link(gst_element_link_many(streammux, pgie, tracker, preprocess,
                                         sgie, sink, nullptr),
                   "live inference chain");

      GstPad* tracker_src = gst_element_get_static_pad(tracker, "src");
      GstPad* sgie_src = gst_element_get_static_pad(sgie, "src");
      if (tracker_src == nullptr || sgie_src == nullptr) {
        if (tracker_src != nullptr) gst_object_unref(tracker_src);
        if (sgie_src != nullptr) gst_object_unref(sgie_src);
        throw std::runtime_error("failed to get live probe pads");
      }
      tracker_probe_id = gst_pad_add_probe(tracker_src, GST_PAD_PROBE_TYPE_BUFFER,
                                           &Impl::on_tracker_buffer, this, nullptr);
      result_probe_id = gst_pad_add_probe(sgie_src, GST_PAD_PROBE_TYPE_BUFFER,
                                          &Impl::on_result_buffer, this, nullptr);
      gst_object_unref(tracker_src);
      gst_object_unref(sgie_src);
      if (tracker_probe_id == 0 || result_probe_id == 0) {
        throw std::runtime_error("failed to install live probes");
      }
    } catch (...) {
      close_graph();
      throw;
    }
  }

  void close_graph() {
    if (pipeline == nullptr) return;
    gst_element_set_state(pipeline, GST_STATE_NULL);
    if (bus_watch_id != 0) {
      g_source_remove(bus_watch_id);
      bus_watch_id = 0;
    }
    if (tracker_probe_id != 0 && tracker != nullptr) {
      GstPad* pad = gst_element_get_static_pad(tracker, "src");
      if (pad != nullptr) {
        gst_pad_remove_probe(pad, tracker_probe_id);
        gst_object_unref(pad);
      }
      tracker_probe_id = 0;
    }
    if (result_probe_id != 0 && sgie != nullptr) {
      GstPad* pad = gst_element_get_static_pad(sgie, "src");
      if (pad != nullptr) {
        gst_pad_remove_probe(pad, result_probe_id);
        gst_object_unref(pad);
      }
      result_probe_id = 0;
    }
    if (mux_sink_pad != nullptr && streammux != nullptr) {
      gst_element_release_request_pad(streammux, mux_sink_pad);
      gst_object_unref(mux_sink_pad);
      mux_sink_pad = nullptr;
    }
    gst_object_unref(pipeline);
    pipeline = nullptr;
    source = nullptr;
    source_queue = nullptr;
    converter = nullptr;
    caps_filter = nullptr;
    streammux = nullptr;
    pgie = nullptr;
    tracker = nullptr;
    preprocess = nullptr;
    sgie = nullptr;
    sink = nullptr;
  }

  static void on_source_pad(GstElement*, GstPad* pad, gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    GstCaps* caps = gst_pad_get_current_caps(pad);
    if (caps == nullptr) caps = gst_pad_query_caps(pad, nullptr);
    if (caps == nullptr || gst_caps_is_empty(caps)) {
      if (caps != nullptr) gst_caps_unref(caps);
      return;
    }
    const GstStructure* structure = gst_caps_get_structure(caps, 0);
    const gchar* name = gst_structure_get_name(structure);
    const GstCapsFeatures* features = gst_caps_get_features(caps, 0);
    const bool is_video = name != nullptr && g_str_has_prefix(name, "video/");
    const bool is_nvmm = features != nullptr &&
                         gst_caps_features_contains(features, "memory:NVMM");
    if (is_video && is_nvmm) {
      GstPad* sink_pad = gst_element_get_static_pad(self->source_queue, "sink");
      if (sink_pad == nullptr ||
          (!gst_pad_is_linked(sink_pad) &&
           gst_pad_link(pad, sink_pad) != GST_PAD_LINK_OK)) {
        self->emit_failure();
        if (self->loop != nullptr) g_main_loop_quit(self->loop);
      } else if (!self->source_connected.exchange(true)) {
        self->emit_operation("source_connect", self->source_connect_started_ns);
      }
      if (sink_pad != nullptr) gst_object_unref(sink_pad);
    } else if (is_video) {
      self->emit_failure();
      if (self->loop != nullptr) g_main_loop_quit(self->loop);
    }
    gst_caps_unref(caps);
  }

  static GstPadProbeReturn on_tracker_buffer(GstPad*, GstPadProbeInfo* info,
                                              gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    NvDsBatchMeta* batch = gst_buffer_get_nvds_batch_meta(buffer);
    if (batch == nullptr) return GST_PAD_PROBE_OK;
    for (NvDsMetaList* frame_item = batch->frame_meta_list; frame_item != nullptr;
         frame_item = frame_item->next) {
      auto* frame = static_cast<NvDsFrameMeta*>(frame_item->data);
      if (frame->frame_num % self->options.sample_every_n == 0) {
        for (NvDsMetaList* object_item = frame->obj_meta_list;
             object_item != nullptr; object_item = object_item->next) {
          auto* object = static_cast<NvDsObjectMeta*>(object_item->data);
          if (object->mask_params.data == nullptr ||
              object->mask_params.size < 15 * sizeof(float)) {
            continue;
          }
          std::array<float, 10> landmarks{};
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            landmarks[landmark * 2] = object->mask_params.data[landmark * 3];
            landmarks[landmark * 2 + 1] =
                object->mask_params.data[landmark * 3 + 1];
          }
          transform_landmarks_from_network(
              landmarks, object->mask_params.width, object->mask_params.height,
              frame->pipeline_width, frame->pipeline_height);
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            object->mask_params.data[landmark * 3] = landmarks[landmark * 2];
            object->mask_params.data[landmark * 3 + 1] =
                landmarks[landmark * 2 + 1];
          }
        }
        continue;
      }
      NvDsMetaList* object_item = frame->obj_meta_list;
      while (object_item != nullptr) {
        NvDsMetaList* next = object_item->next;
        nvds_remove_obj_meta_from_frame(
            frame, static_cast<NvDsObjectMeta*>(object_item->data));
        object_item = next;
      }
    }
    return GST_PAD_PROBE_OK;
  }

  static GstPadProbeReturn on_result_buffer(GstPad*, GstPadProbeInfo* info,
                                             gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    NvDsBatchMeta* batch = gst_buffer_get_nvds_batch_meta(buffer);
    if (batch == nullptr) return GST_PAD_PROBE_OK;
    ObjectEmbeddingMap embeddings;
    {
      std::lock_guard lock(self->embedding_mutex);
      const auto found = self->arcface_outputs.find(buffer);
      if (found != self->arcface_outputs.end()) {
        embeddings = std::move(found->second);
        self->arcface_outputs.erase(found);
      }
    }
    const std::uint64_t inference_started = monotonic_ns();
    std::uint64_t window_objects = 0;
    for (NvDsMetaList* frame_item = batch->frame_meta_list; frame_item != nullptr;
         frame_item = frame_item->next) {
      const auto* frame = static_cast<const NvDsFrameMeta*>(frame_item->data);
      ++self->counters.decoded_frames;
      std::vector<TrackedBox> current_tracks;
      if (!self->first_frame.exchange(true)) {
        notify(self->callbacks.on_state, LiveRuntimeState::Active);
        self->emit_operation("first_frame", self->source_connect_started_ns);
      }
      for (NvDsMetaList* object_item = frame->obj_meta_list;
           object_item != nullptr; object_item = object_item->next) {
        const auto* object = static_cast<const NvDsObjectMeta*>(object_item->data);
        if (object->object_id == UNTRACKED_OBJECT_ID) continue;
        ++self->counters.tracked_objects;
        current_tracks.push_back({object->object_id, object->rect_params.left,
                                  object->rect_params.top,
                                  object->rect_params.width,
                                  object->rect_params.height});
        if (object->mask_params.data == nullptr ||
            object->mask_params.size < 15 * sizeof(float)) {
          continue;
        }
        ++self->counters.eligible_object_count;
        ++window_objects;
        const auto embedding = embeddings.find(object);
        if (embedding == embeddings.end()) {
          ++self->counters.missing_embedding_count;
          continue;
        }

        double norm_squared = 0.0;
        for (const float value : embedding->second) {
          norm_squared += static_cast<double>(value) * value;
        }
        const double norm = std::sqrt(norm_squared);
        if (self->counters.embedding_norm_samples == 0) {
          self->counters.embedding_norm_min = norm;
          self->counters.embedding_norm_max = norm;
        } else {
          self->counters.embedding_norm_min =
              std::min(self->counters.embedding_norm_min, norm);
          self->counters.embedding_norm_max =
              std::max(self->counters.embedding_norm_max, norm);
        }
        self->counters.embedding_norm_sum += norm;
        ++self->counters.embedding_norm_samples;
        if (self->previous_embedding.has_value()) {
          double cosine = 0.0;
          for (std::size_t index = 0; index < embedding->second.size(); ++index) {
            cosine += static_cast<double>((*self->previous_embedding)[index]) *
                      embedding->second[index];
          }
          self->counters.embedding_cosine_sum += cosine;
          ++self->counters.embedding_cosine_samples;
        }
        self->previous_embedding = embedding->second;

        LiveObservation observation;
        observation.timestamp_ns = GST_CLOCK_TIME_IS_VALID(frame->buf_pts)
                                       ? frame->buf_pts
                                       : monotonic_ns();
        observation.detection_ordinal = self->next_detection_ordinal++;
        observation.frame_width = frame->pipeline_width;
        observation.frame_height = frame->pipeline_height;
        const float frame_width = static_cast<float>(observation.frame_width);
        const float frame_height = static_cast<float>(observation.frame_height);
        const float left = clamp_value(object->rect_params.left, 0.0F, frame_width);
        const float top = clamp_value(object->rect_params.top, 0.0F, frame_height);
        const float right = clamp_value(object->rect_params.left +
                                            object->rect_params.width,
                                        left, frame_width);
        const float bottom = clamp_value(object->rect_params.top +
                                             object->rect_params.height,
                                         top, frame_height);
        observation.bbox = {left, top, right - left, bottom - top};
        observation.detector_confidence =
            clamp_value(object->confidence, 0.0F, 1.0F);
        for (std::size_t landmark = 0; landmark < 5; ++landmark) {
          observation.landmarks[landmark * 2] =
              object->mask_params.data[landmark * 3];
          observation.landmarks[landmark * 2 + 1] =
              object->mask_params.data[landmark * 3 + 1];
          observation.landmark_confidences[landmark] = clamp_value(
              object->mask_params.data[landmark * 3 + 2], 0.0F, 1.0F);
        }
        observation.embedding = embedding->second;
        observation.aligned_jpeg = copy_aligned_jpeg(*object);
        observation.quality = measure_quality(observation, QualityConfig{});
        if (!observation.quality.accepted) {
          ++self->counters.invalid_embedding_count;
          continue;
        }
        ++self->counters.embedding_count;
        self->emit_evidence(object->object_id, std::move(observation));
      }
      self->update_tracker_switches(current_tracks);
    }
    if (self->counters.decoded_frames == 1 ||
        self->counters.decoded_frames % 120 == 0) {
      self->emit_operation(
          "inference_window", inference_started,
          {{"batch_size", std::int64_t{1}},
           {"object_count", static_cast<std::int64_t>(window_objects)}});
    }
    self->counters.pipeline_warnings = self->pipeline_warnings.load();
    self->counters.pipeline_errors = self->pipeline_errors.load();
    notify(self->callbacks.on_metrics, self->counters);
    return GST_PAD_PROBE_OK;
  }

  void emit_evidence(std::uint64_t tracker_id, LiveObservation observation) {
    TrackEvidenceEvent event;
    {
      std::lock_guard lock(track_mutex);
      TrackRuntime& track = tracks.try_emplace(tracker_id).first->second;
      if (track.first_seen_ns == 0) track.first_seen_ns = observation.timestamp_ns;
      track.last_seen_ns = observation.timestamp_ns;
      const auto change = track.evidence.consider(observation);
      if (change == EvidenceChange::Rejected || change == EvidenceChange::Unchanged) {
        return;
      }
      ++track.revision;
      event = {header("track_evidence"), tracker_id, track.revision,
               track.first_seen_ns, track.last_seen_ns,
               track.evidence.observations(), observation.aligned_jpeg};
    }
    ++counters.emitted_evidence;
    notify(callbacks.on_evidence, event);
  }

  void update_tracker_switches(const std::vector<TrackedBox>& current_tracks) {
    std::vector<bool> matched(previous_tracks.size(), false);
    for (const auto& current : current_tracks) {
      float best_overlap = 0.0F;
      std::size_t best_index = previous_tracks.size();
      for (std::size_t index = 0; index < previous_tracks.size(); ++index) {
        if (matched[index]) continue;
        const float overlap = intersection_over_union(current, previous_tracks[index]);
        if (overlap > best_overlap) {
          best_overlap = overlap;
          best_index = index;
        }
      }
      if (best_index != previous_tracks.size() && best_overlap >= 0.5F) {
        matched[best_index] = true;
        if (current.tracker_id != previous_tracks[best_index].tracker_id) {
          ++counters.tracker_id_switches;
        }
      }
    }
    previous_tracks = current_tracks;
  }

  static void on_sgie_output(GstBuffer* buffer, NvDsInferNetworkInfo*,
                             NvDsInferLayerInfo* layers, guint num_layers,
                             guint batch_size, gpointer user_data) {
    const float* output = nullptr;
    for (guint index = 0; index < num_layers; ++index) {
      if (layers[index].layerName != nullptr &&
          std::strcmp(layers[index].layerName, "output") == 0 &&
          layers[index].dataType == FLOAT &&
          layers[index].inferDims.numElements == 512 &&
          layers[index].buffer != nullptr) {
        output = static_cast<const float*>(layers[index].buffer);
        break;
      }
    }
    NvDsBatchMeta* batch = gst_buffer_get_nvds_batch_meta(buffer);
    if (output == nullptr || batch == nullptr) return;
    std::vector<const void*> objects;
    objects.reserve(batch_size);
    for (NvDsMetaList* user_item = batch->batch_user_meta_list;
         user_item != nullptr; user_item = user_item->next) {
      const auto* user_meta = static_cast<const NvDsUserMeta*>(user_item->data);
      if (user_meta == nullptr ||
          user_meta->base_meta.meta_type != NVDS_PREPROCESS_BATCH_META ||
          user_meta->user_meta_data == nullptr) {
        continue;
      }
      const auto* preprocess_meta =
          static_cast<const GstNvDsPreProcessBatchMeta*>(
              user_meta->user_meta_data);
      for (const NvDsRoiMeta& roi : preprocess_meta->roi_vector) {
        if (roi.object_meta != nullptr) objects.push_back(roi.object_meta);
      }
    }
    auto mapped = map_embedding_rows(output, batch_size, objects);
    if (!mapped.has_value()) return;
    auto* self = static_cast<Impl*>(user_data);
    std::lock_guard lock(self->embedding_mutex);
    self->arcface_outputs.insert_or_assign(buffer, std::move(*mapped));
  }

  static gboolean on_bus(GstBus*, GstMessage* message, gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
      GError* error = nullptr;
      gchar* debug = nullptr;
      gst_message_parse_error(message, &error, &debug);
      if (error != nullptr) g_error_free(error);
      g_free(debug);
      self->emit_failure();
      g_main_loop_quit(self->loop);
      return G_SOURCE_REMOVE;
    }
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_WARNING) {
      GError* warning = nullptr;
      gchar* debug = nullptr;
      gst_message_parse_warning(message, &warning, &debug);
      if (warning != nullptr) g_error_free(warning);
      g_free(debug);
      self->pipeline_warnings.fetch_add(1);
      return G_SOURCE_CONTINUE;
    }
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS) {
      self->emit_failure();
      g_main_loop_quit(self->loop);
      return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
  }

  LivePipelineCallbacks callbacks;
  LivePipelineOptions options;
  LivePipelineCounters counters;
  GstElement* pipeline{};
  GstElement* source{};
  GstElement* source_queue{};
  GstElement* converter{};
  GstElement* caps_filter{};
  GstElement* streammux{};
  GstElement* pgie{};
  GstElement* tracker{};
  GstElement* preprocess{};
  GstElement* sgie{};
  GstElement* sink{};
  GstPad* mux_sink_pad{};
  GMainLoop* loop{};
  guint bus_watch_id{};
  gulong tracker_probe_id{};
  gulong result_probe_id{};
  std::thread worker;
  std::atomic_bool started{};
  std::atomic_bool stop_requested{};
  std::atomic_bool failed{};
  std::atomic_bool source_connected{};
  std::atomic_bool first_frame{};
  std::atomic_uint64_t next_sequence{};
  std::atomic_uint64_t pipeline_warnings{};
  std::atomic_uint64_t pipeline_errors{};
  std::uint64_t source_connect_started_ns{};
  std::uint64_t next_detection_ordinal{};
  StopReason stop_reason{StopReason::Requested};
  std::mutex embedding_mutex;
  std::unordered_map<GstBuffer*, ObjectEmbeddingMap> arcface_outputs;
  std::mutex track_mutex;
  std::unordered_map<std::uint64_t, TrackRuntime> tracks;
  std::vector<TrackedBox> previous_tracks;
  std::optional<std::array<float, 512>> previous_embedding;
};

LivePipeline::LivePipeline(LivePipelineCallbacks callbacks)
    : impl_(new Impl(std::move(callbacks))) {}

LivePipeline::~LivePipeline() { delete impl_; }

void LivePipeline::start(const LivePipelineOptions& options) {
  impl_->start(options);
}

bool LivePipeline::apply_assignment(const IdentityAssignment& assignment) {
  return impl_->apply_assignment(assignment);
}

void LivePipeline::stop(StopReason reason) { impl_->stop(reason); }

void LivePipeline::close() { impl_->close(); }

}  // namespace mvision
