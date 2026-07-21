#include "mvision/video_pipeline.hpp"

#include "mvision/aligned_evidence_meta.hpp"

#include <gst/gst.h>
#include <gstnvdsinfer.h>
#include <gstnvdsmeta.h>
#include <nvdspreprocess_meta.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mvision {
namespace {

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

std::vector<std::uint8_t> copy_representative_jpeg(const NvDsObjectMeta& object) {
  for (NvDsMetaList* item = object.obj_user_meta_list; item != nullptr; item = item->next) {
    const auto* user_meta = static_cast<const NvDsUserMeta*>(item->data);
    if (user_meta != nullptr && user_meta->base_meta.meta_type == aligned_jpeg_meta_type() &&
        user_meta->user_meta_data != nullptr) {
      return static_cast<const AlignedJpegMeta*>(user_meta->user_meta_data)->bytes;
    }
  }
  return {};
}

float clamp_value(float value, float minimum, float maximum) {
  return std::max(minimum, std::min(maximum, value));
}

}  // namespace

std::optional<ObjectEmbeddingMap> map_embedding_rows(
    const float* output, std::size_t row_count,
    const std::vector<const void*>& objects) {
  if (output == nullptr || row_count == 0 || objects.size() != row_count) {
    return std::nullopt;
  }
  ObjectEmbeddingMap mapped;
  mapped.reserve(row_count);
  for (std::size_t row = 0; row < row_count; ++row) {
    if (objects[row] == nullptr) {
      return std::nullopt;
    }
    std::array<float, 512> embedding{};
    float norm_squared = 0.0F;
    for (std::size_t index = 0; index < embedding.size(); ++index) {
      const float value = output[row * embedding.size() + index];
      if (!std::isfinite(value)) {
        return std::nullopt;
      }
      embedding[index] = value;
      norm_squared += value * value;
    }
    if (!std::isfinite(norm_squared) || norm_squared <= 0.0F) {
      return std::nullopt;
    }
    const float inverse_norm = 1.0F / std::sqrt(norm_squared);
    for (float& value : embedding) {
      value *= inverse_norm;
    }
    if (!mapped.emplace(objects[row], embedding).second) {
      return std::nullopt;
    }
  }
  return mapped;
}

void transform_landmarks_from_network(std::array<float, 10>& landmarks,
                                      std::uint32_t network_width,
                                      std::uint32_t network_height,
                                      std::uint32_t frame_width,
                                      std::uint32_t frame_height) {
  if (network_width == 0 || network_height == 0 || frame_width == 0 || frame_height == 0) {
    return;
  }
  const float scale = std::min(static_cast<float>(network_width) / frame_width,
                               static_cast<float>(network_height) / frame_height);
  const float padding_x = (network_width - frame_width * scale) * 0.5F;
  const float padding_y = (network_height - frame_height * scale) * 0.5F;
  for (std::size_t landmark = 0; landmark < 5; ++landmark) {
    landmarks[landmark * 2] = clamp_value(
        (landmarks[landmark * 2] - padding_x) / scale, 0.0F,
        static_cast<float>(frame_width));
    landmarks[landmark * 2 + 1] = clamp_value(
        (landmarks[landmark * 2 + 1] - padding_y) / scale, 0.0F,
        static_cast<float>(frame_height));
  }
}

void VideoTrackAccumulator::add(const VideoObservation& observation,
                                std::uint32_t frame_width,
                                std::uint32_t frame_height) {
  TrackState& track = tracks_[observation.tracker_id];
  track.tracker_id = observation.tracker_id;
  VideoDetection detection = observation.detection;
  const float right = clamp_value(
      detection.x + detection.width, 0.0F, static_cast<float>(frame_width));
  const float bottom = clamp_value(
      detection.y + detection.height, 0.0F, static_cast<float>(frame_height));
  detection.x = clamp_value(detection.x, 0.0F, static_cast<float>(frame_width));
  detection.y = clamp_value(detection.y, 0.0F, static_cast<float>(frame_height));
  detection.width = std::max(0.0F, right - detection.x);
  detection.height = std::max(0.0F, bottom - detection.y);
  track.detections.push_back(detection);
  const float quality = detection.detector_confidence *
                        std::sqrt(detection.width * detection.height);
  track.ranked_embeddings.push_back({quality, detection.frame, observation.embedding});
  std::stable_sort(
      track.ranked_embeddings.begin(), track.ranked_embeddings.end(),
      [](const RankedEmbedding& left, const RankedEmbedding& right) {
        return left.quality != right.quality ? left.quality > right.quality
                                             : left.frame < right.frame;
      });
  constexpr std::size_t kTopObservations = 5;
  if (track.ranked_embeddings.size() > kTopObservations) {
    track.ranked_embeddings.resize(kTopObservations);
  }
  if (!observation.representative_jpeg.empty() &&
      detection.detector_confidence > track.representative_score) {
    track.representative_score = detection.detector_confidence;
    track.representative_jpeg = observation.representative_jpeg;
  }
}

std::vector<VideoTrackOutput> VideoTrackAccumulator::finish() const {
  std::vector<VideoTrackOutput> output;
  output.reserve(tracks_.size());
  for (const auto& [tracker_id, state] : tracks_) {
    if (state.ranked_embeddings.empty() || state.detections.empty()) {
      continue;
    }
    VideoTrackOutput track;
    track.tracker_id = tracker_id;
    double norm_squared = 0.0;
    for (std::size_t index = 0; index < track.embedding.size(); ++index) {
      double sum = 0.0;
      for (const auto& ranked : state.ranked_embeddings) {
        sum += ranked.embedding[index];
      }
      const double mean = sum / state.ranked_embeddings.size();
      track.embedding[index] = static_cast<float>(mean);
      norm_squared += mean * mean;
    }
    if (norm_squared <= 0.0 || !std::isfinite(norm_squared)) {
      continue;
    }
    const float inverse_norm = static_cast<float>(1.0 / std::sqrt(norm_squared));
    for (float& value : track.embedding) {
      value *= inverse_norm;
    }
    track.representative_jpeg = state.representative_jpeg;
    track.detections = state.detections;
    std::stable_sort(track.detections.begin(), track.detections.end(),
                     [](const VideoDetection& left, const VideoDetection& right) {
                       return left.frame < right.frame;
                     });
    output.push_back(std::move(track));
  }
  std::stable_sort(output.begin(), output.end(), [](const auto& left, const auto& right) {
    const auto left_frame = left.detections.front().frame;
    const auto right_frame = right.detections.front().frame;
    return left_frame != right_frame ? left_frame < right_frame
                                     : left.tracker_id < right.tracker_id;
  });
  return output;
}

class DeepStreamVideoPipeline::Impl {
 public:
  explicit Impl(VideoPipelineOptions selected_options) : options(std::move(selected_options)) {
    static std::once_flag gst_init_flag;
    std::call_once(gst_init_flag, [] { gst_init(nullptr, nullptr); });
    if (options.sample_every_n == 0 || options.width == 0 || options.height == 0 ||
        options.fps <= 0.0) {
      throw std::invalid_argument("invalid video pipeline options");
    }
    build();
  }

  ~Impl() { close(); }

  void run(const VideoEventCallback& selected_callback,
           std::atomic_bool& selected_cancellation) {
    callback = &selected_callback;
    cancellation = &selected_cancellation;
    loop = g_main_loop_new(nullptr, FALSE);
    GstBus* bus = gst_element_get_bus(pipeline);
    bus_watch_id = gst_bus_add_watch(bus, &Impl::on_bus, this);
    gst_object_unref(bus);
    cancel_watch_id = g_timeout_add(100, &Impl::on_cancel_watch, this);
    const GstStateChangeReturn state = gst_element_set_state(pipeline, GST_STATE_PLAYING);
    if (state == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("failed to start video pipeline");
    }
    g_main_loop_run(loop);
    gst_element_set_state(pipeline, GST_STATE_NULL);
    if (cancellation->load()) {
      return;
    }
    if (!error_message.empty()) {
      throw std::runtime_error(error_message);
    }
    if (!saw_eos) {
      throw std::runtime_error("video pipeline stopped without EOS");
    }
    const auto tracks = accumulator.finish();
    g_printerr(
        "video diagnostics: objects=%lu untracked=%lu roi_embeddings=%lu "
        "missing_embeddings=%lu observations=%lu\n",
        static_cast<unsigned long>(object_count),
        static_cast<unsigned long>(untracked_object_count),
        static_cast<unsigned long>(roi_embedding_count),
        static_cast<unsigned long>(missing_embedding_count),
        static_cast<unsigned long>(observation_count));
    for (const auto& track : tracks) {
      (*callback)(encode_video_event(track));
    }
    (*callback)(encode_video_event(
        VideoCompleted{decoded_frames, processed_frames, tracks.size()}));
  }

 private:
  void build() {
    pipeline = gst_pipeline_new("mvision-video-pipeline");
    source = make_element("uridecodebin", "video-source");
    converter = make_element("nvvideoconvert", "video-converter");
    caps_filter = make_element("capsfilter", "nvmm-filter");
    streammux = make_element("nvstreammux", "video-muxer");
    pgie = make_element("nvinfer", "video-face-pgie");
    tracker = make_element("nvtracker", "video-face-tracker");
    preprocess = make_element("nvdspreprocess", "video-face-preprocess");
    sgie = make_element("nvinfer", "video-face-sgie");
    sink = make_element("fakesink", "video-sink");

    gchar* uri = gst_filename_to_uri(options.video_path.c_str(), nullptr);
    if (uri == nullptr) {
      throw std::runtime_error("failed to convert video path to URI");
    }
    g_object_set(source, "uri", uri, nullptr);
    g_free(uri);
    g_signal_connect(source, "pad-added", G_CALLBACK(&Impl::on_decode_pad), this);

    GstCaps* caps = gst_caps_from_string("video/x-raw(memory:NVMM),format=NV12");
    g_object_set(caps_filter, "caps", caps, nullptr);
    gst_caps_unref(caps);
    g_object_set(streammux, "gpu-id", options.gpu_id, "batch-size", 1U, "width",
                 options.width, "height", options.height, "live-source", FALSE,
                 "batched-push-timeout", 40000, "enable-padding", TRUE, nullptr);
    g_object_set(pgie, "config-file-path", options.pgie_config_path.c_str(), "interval",
                 options.sample_every_n - 1, nullptr);
    g_object_set(tracker, "gpu-id", options.gpu_id, "tracker-width", 640U,
                 "tracker-height", 384U, "ll-lib-file",
                 "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
                 "ll-config-file", options.tracker_config_path.c_str(), nullptr);
    g_object_set(preprocess, "config-file", options.preprocess_config_path.c_str(), nullptr);
    g_object_set(sgie, "config-file-path", options.sgie_config_path.c_str(),
                 "input-tensor-meta", TRUE, "output-tensor-meta", TRUE,
                 "raw-output-generated-callback", &Impl::on_sgie_output,
                 "raw-output-generated-userdata", this, nullptr);
    g_object_set(sink, "sync", FALSE, "async", FALSE, "enable-last-sample", FALSE, nullptr);

    gst_bin_add_many(GST_BIN(pipeline), source, converter, caps_filter, streammux, pgie,
                     tracker, preprocess, sgie, sink, nullptr);
    require_link(gst_element_link(converter, caps_filter), "converter to caps filter");
    GstPad* source_pad = gst_element_get_static_pad(caps_filter, "src");
    mux_sink_pad = gst_element_request_pad_simple(streammux, "sink_0");
    if (source_pad == nullptr || mux_sink_pad == nullptr ||
        gst_pad_link(source_pad, mux_sink_pad) != GST_PAD_LINK_OK) {
      if (source_pad != nullptr) {
        gst_object_unref(source_pad);
      }
      throw std::runtime_error("failed to link video source to nvstreammux");
    }
    gst_object_unref(source_pad);
    require_link(gst_element_link_many(streammux, pgie, tracker, preprocess, sgie, sink,
                                       nullptr),
                 "video inference chain");

    GstPad* tracker_src = gst_element_get_static_pad(tracker, "src");
    GstPad* sgie_src = gst_element_get_static_pad(sgie, "src");
    if (tracker_src == nullptr || sgie_src == nullptr) {
      throw std::runtime_error("failed to get video probe pads");
    }
    tracker_probe_id = gst_pad_add_probe(
        tracker_src, GST_PAD_PROBE_TYPE_BUFFER, &Impl::on_tracker_buffer, this, nullptr);
    result_probe_id = gst_pad_add_probe(sgie_src, GST_PAD_PROBE_TYPE_BUFFER,
                                        &Impl::on_result_buffer, this, nullptr);
    gst_object_unref(tracker_src);
    gst_object_unref(sgie_src);
  }

  void close() {
    if (pipeline == nullptr) {
      return;
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    if (bus_watch_id != 0) {
      g_source_remove(bus_watch_id);
      bus_watch_id = 0;
    }
    if (cancel_watch_id != 0) {
      g_source_remove(cancel_watch_id);
      cancel_watch_id = 0;
    }
    if (loop != nullptr) {
      g_main_loop_unref(loop);
      loop = nullptr;
    }
    if (mux_sink_pad != nullptr) {
      gst_element_release_request_pad(streammux, mux_sink_pad);
      gst_object_unref(mux_sink_pad);
      mux_sink_pad = nullptr;
    }
    gst_object_unref(pipeline);
    pipeline = nullptr;
  }

  static void on_decode_pad(GstElement*, GstPad* pad, gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    GstCaps* caps = gst_pad_get_current_caps(pad);
    if (caps == nullptr) {
      caps = gst_pad_query_caps(pad, nullptr);
    }
    if (caps == nullptr || gst_caps_is_empty(caps)) {
      if (caps != nullptr) {
        gst_caps_unref(caps);
      }
      return;
    }
    const GstStructure* structure = gst_caps_get_structure(caps, 0);
    const gchar* name = gst_structure_get_name(structure);
    const GstCapsFeatures* features = gst_caps_get_features(caps, 0);
    const bool is_video = name != nullptr && g_str_has_prefix(name, "video/");
    const bool is_nvmm = features != nullptr &&
                         gst_caps_features_contains(features, "memory:NVMM");
    if (is_video && is_nvmm) {
      GstPad* sink_pad = gst_element_get_static_pad(self->converter, "sink");
      if (!gst_pad_is_linked(sink_pad) && gst_pad_link(pad, sink_pad) != GST_PAD_LINK_OK) {
        self->error_message = "failed to link hardware decoder output";
        if (self->loop != nullptr) {
          g_main_loop_quit(self->loop);
        }
      }
      gst_object_unref(sink_pad);
    } else if (is_video) {
      self->error_message = "video decoder did not produce NVMM memory";
      if (self->loop != nullptr) {
        g_main_loop_quit(self->loop);
      }
    }
    gst_caps_unref(caps);
  }

  static GstPadProbeReturn on_tracker_buffer(GstPad*, GstPadProbeInfo* info,
                                              gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    NvDsBatchMeta* batch = gst_buffer_get_nvds_batch_meta(buffer);
    if (batch == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    for (NvDsMetaList* frame_item = batch->frame_meta_list; frame_item != nullptr;
         frame_item = frame_item->next) {
      auto* frame = static_cast<NvDsFrameMeta*>(frame_item->data);
      if (frame->frame_num % self->options.sample_every_n == 0) {
        for (NvDsMetaList* object_item = frame->obj_meta_list; object_item != nullptr;
             object_item = object_item->next) {
          auto* object = static_cast<NvDsObjectMeta*>(object_item->data);
          if (object->mask_params.data == nullptr ||
              object->mask_params.size < 15 * sizeof(float)) {
            continue;
          }
          std::array<float, 10> landmarks{};
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            landmarks[landmark * 2] = object->mask_params.data[landmark * 3];
            landmarks[landmark * 2 + 1] = object->mask_params.data[landmark * 3 + 1];
          }
          transform_landmarks_from_network(
              landmarks, object->mask_params.width, object->mask_params.height,
              frame->pipeline_width, frame->pipeline_height);
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            object->mask_params.data[landmark * 3] = landmarks[landmark * 2];
            object->mask_params.data[landmark * 3 + 1] = landmarks[landmark * 2 + 1];
          }
        }
        continue;
      }
      NvDsMetaList* object_item = frame->obj_meta_list;
      while (object_item != nullptr) {
        NvDsMetaList* next = object_item->next;
        nvds_remove_obj_meta_from_frame(frame,
                                        static_cast<NvDsObjectMeta*>(object_item->data));
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
    if (batch == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    ObjectEmbeddingMap roi_embeddings;
    {
      std::lock_guard lock(self->output_mutex);
      const auto found = self->arcface_outputs.find(buffer);
      if (found != self->arcface_outputs.end()) {
        roi_embeddings = std::move(found->second);
        self->arcface_outputs.erase(found);
      }
    }
    self->roi_embedding_count += roi_embeddings.size();
    for (NvDsMetaList* frame_item = batch->frame_meta_list; frame_item != nullptr;
         frame_item = frame_item->next) {
      const auto* frame = static_cast<const NvDsFrameMeta*>(frame_item->data);
      const auto frame_number =
          static_cast<std::uint64_t>(std::max(0, frame->frame_num));
      self->decoded_frames = std::max(self->decoded_frames, frame_number + 1);
      ++self->processed_frames;
      for (NvDsMetaList* object_item = frame->obj_meta_list; object_item != nullptr;
           object_item = object_item->next) {
        const auto* object = static_cast<const NvDsObjectMeta*>(object_item->data);
        ++self->object_count;
        if (object->object_id == UNTRACKED_OBJECT_ID) {
          ++self->untracked_object_count;
          continue;
        }
        VideoObservation observation;
        observation.tracker_id = object->object_id;
        const auto roi_embedding = roi_embeddings.find(object);
        if (roi_embedding == roi_embeddings.end()) {
          ++self->missing_embedding_count;
          continue;
        }
        observation.embedding = roi_embedding->second;
        const double timestamp = GST_CLOCK_TIME_IS_VALID(frame->buf_pts)
                                     ? static_cast<double>(frame->buf_pts) / GST_SECOND
                                     : static_cast<double>(frame_number) / self->options.fps;
        observation.detection = {
            frame_number,
            timestamp,
            object->rect_params.left,
            object->rect_params.top,
            object->rect_params.width,
            object->rect_params.height,
            clamp_value(object->confidence, 0.0F, 1.0F),
        };
        if (object->mask_params.data != nullptr &&
            object->mask_params.size >= 15 * sizeof(float)) {
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            observation.detection.landmarks[landmark * 2] =
                object->mask_params.data[landmark * 3];
            observation.detection.landmarks[landmark * 2 + 1] =
                object->mask_params.data[landmark * 3 + 1];
          }
        }
        observation.representative_jpeg = copy_representative_jpeg(*object);
        self->accumulator.add(observation, self->options.width, self->options.height);
        ++self->observation_count;
      }
      if (self->callback != nullptr) {
        const float progress = self->options.total_frames == 0
                                   ? 0.0F
                                   : std::min(
                                         100.0F,
                                         100.0F * static_cast<float>(self->decoded_frames) /
                                             static_cast<float>(self->options.total_frames));
        (*self->callback)(encode_video_event(VideoProgress{
            self->decoded_frames, self->processed_frames, self->options.total_frames,
            progress}));
      }
    }
    return GST_PAD_PROBE_OK;
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
    if (output == nullptr || batch == nullptr) {
      return;
    }
    std::vector<const void*> objects;
    objects.reserve(batch_size);
    for (NvDsMetaList* user_item = batch->batch_user_meta_list; user_item != nullptr;
         user_item = user_item->next) {
      const auto* user_meta = static_cast<const NvDsUserMeta*>(user_item->data);
      if (user_meta == nullptr ||
          user_meta->base_meta.meta_type != NVDS_PREPROCESS_BATCH_META ||
          user_meta->user_meta_data == nullptr) {
        continue;
      }
      const auto* preprocess_meta =
          static_cast<const GstNvDsPreProcessBatchMeta*>(user_meta->user_meta_data);
      for (const NvDsRoiMeta& roi : preprocess_meta->roi_vector) {
        if (roi.object_meta != nullptr) {
          objects.push_back(roi.object_meta);
        }
      }
    }
    auto mapped = map_embedding_rows(output, batch_size, objects);
    if (!mapped.has_value()) {
      return;
    }
    auto* self = static_cast<Impl*>(user_data);
    std::lock_guard lock(self->output_mutex);
    self->arcface_outputs.insert_or_assign(buffer, std::move(*mapped));
  }

  static gboolean on_bus(GstBus*, GstMessage* message, gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS) {
      self->saw_eos = true;
      g_main_loop_quit(self->loop);
      return G_SOURCE_REMOVE;
    }
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
      GError* error = nullptr;
      gchar* debug = nullptr;
      gst_message_parse_error(message, &error, &debug);
      self->error_message = error != nullptr ? error->message : "unknown GStreamer error";
      if (error != nullptr) {
        g_error_free(error);
      }
      g_free(debug);
      g_main_loop_quit(self->loop);
      return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
  }

  static gboolean on_cancel_watch(gpointer user_data) {
    auto* self = static_cast<Impl*>(user_data);
    if (self->cancellation != nullptr && self->cancellation->load()) {
      g_main_loop_quit(self->loop);
      return G_SOURCE_REMOVE;
    }
    return G_SOURCE_CONTINUE;
  }

  VideoPipelineOptions options;
  VideoTrackAccumulator accumulator;
  const VideoEventCallback* callback{};
  std::atomic_bool* cancellation{};
  GstElement* pipeline{};
  GstElement* source{};
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
  guint cancel_watch_id{};
  gulong tracker_probe_id{};
  gulong result_probe_id{};
  std::uint64_t decoded_frames{};
  std::uint64_t processed_frames{};
  std::uint64_t object_count{};
  std::uint64_t untracked_object_count{};
  std::uint64_t roi_embedding_count{};
  std::uint64_t missing_embedding_count{};
  std::uint64_t observation_count{};
  std::mutex output_mutex;
  std::unordered_map<GstBuffer*, ObjectEmbeddingMap> arcface_outputs;
  bool saw_eos{};
  std::string error_message;
};

DeepStreamVideoPipeline::DeepStreamVideoPipeline(VideoPipelineOptions options)
    : impl_(new Impl(std::move(options))) {}

DeepStreamVideoPipeline::~DeepStreamVideoPipeline() { delete impl_; }

void DeepStreamVideoPipeline::run(const VideoEventCallback& callback,
                                  std::atomic_bool& cancellation_requested) {
  impl_->run(callback, cancellation_requested);
}

}  // namespace mvision
