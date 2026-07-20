#include "mvision/image_source_pool.hpp"
#include "mvision/aligned_evidence_meta.hpp"

#include <gst/app/gstappsrc.h>
#include <gst/gst.h>
#include <gstnvdsinfer.h>
#include <gstnvdsmeta.h>
#include <nvdspreprocess_meta.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iterator>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mvision {
namespace {

GstElement *make_element(const char *factory, const char *name) {
  GstElement *element = gst_element_factory_make(factory, name);
  if (element == nullptr) {
    throw std::runtime_error(std::string("missing GStreamer element: ") + factory);
  }
  return element;
}

void require_link(bool linked, const char *description) {
  if (!linked) {
    throw std::runtime_error(std::string("failed to link ") + description);
  }
}

bool copy_arcface_embedding(NvDsMetaList *user_meta_list,
                            std::array<float, 512> &embedding) {
  for (NvDsMetaList *item = user_meta_list; item != nullptr; item = item->next) {
    const auto *user_meta = static_cast<const NvDsUserMeta *>(item->data);
    if (user_meta->base_meta.meta_type != NVDSINFER_TENSOR_OUTPUT_META ||
        user_meta->user_meta_data == nullptr) {
      continue;
    }
    const auto *tensor_meta =
        static_cast<const NvDsInferTensorMeta *>(user_meta->user_meta_data);
    if (tensor_meta->unique_id != 2) {
      continue;
    }
    for (guint layer_index = 0; layer_index < tensor_meta->num_output_layers; ++layer_index) {
      const NvDsInferLayerInfo &layer = tensor_meta->output_layers_info[layer_index];
        if (layer.layerName != nullptr && std::strcmp(layer.layerName, "output") == 0 &&
            layer.dataType == FLOAT && layer.inferDims.numElements == embedding.size() &&
            tensor_meta->out_buf_ptrs_host[layer_index] != nullptr) {
          std::memcpy(embedding.data(), tensor_meta->out_buf_ptrs_host[layer_index],
                      sizeof(embedding));
          float norm_squared = 0.0F;
          for (const float value : embedding) {
            norm_squared += value * value;
          }
          if (norm_squared <= 0.0F) {
            return false;
          }
          const float inverse_norm = 1.0F / std::sqrt(norm_squared);
          for (float &value : embedding) {
            value *= inverse_norm;
          }
          return true;
      }
    }
  }
  return false;
}

bool copy_arcface_embedding(const NvDsObjectMeta &object,
                            std::array<float, 512> &embedding) {
  return copy_arcface_embedding(object.obj_user_meta_list, embedding);
}

bool copy_aligned_jpeg(const NvDsObjectMeta &object, std::vector<std::uint8_t> &jpeg) {
  for (NvDsMetaList *item = object.obj_user_meta_list; item != nullptr; item = item->next) {
    const auto *user_meta = static_cast<const NvDsUserMeta *>(item->data);
    if (user_meta->base_meta.meta_type == aligned_jpeg_meta_type() &&
        user_meta->user_meta_data != nullptr) {
      jpeg = static_cast<const AlignedJpegMeta *>(user_meta->user_meta_data)->bytes;
      return true;
    }
  }
  return false;
}

}  // namespace

struct PersistentJpegPipeline::Impl {
  struct SourceSlot {
    GstElement *appsrc;
    GstPad *mux_sink_pad;
  };

  Impl(int selected_gpu, std::uint32_t selected_batch_size, std::string selected_pgie_config,
       std::string selected_preprocess_config, std::string selected_sgie_config)
      : gpu_id(selected_gpu),
        batch_size(selected_batch_size),
        pgie_config_path(std::move(selected_pgie_config)),
        preprocess_config_path(std::move(selected_preprocess_config)),
        sgie_config_path(std::move(selected_sgie_config)) {
    static std::once_flag gst_init_flag;
    std::call_once(gst_init_flag, [] { gst_init(nullptr, nullptr); });
    build();
  }

  ~Impl() { close(); }

  void build() {
    pipeline = gst_pipeline_new("mvision-jpeg-pipeline");
    if (pipeline == nullptr) {
      throw std::runtime_error("failed to create GStreamer pipeline");
    }

    streammux = make_element("nvstreammux", "stream-muxer");
    sink = make_element("fakesink", "pipeline-sink");
    if (!pgie_config_path.empty()) {
      pgie = make_element("nvinfer", "yolov8-face-pgie");
      g_object_set(pgie, "config-file-path", pgie_config_path.c_str(), nullptr);
    }
    if (!preprocess_config_path.empty()) {
      if (pgie == nullptr) {
        throw std::runtime_error("nvdspreprocess requires a configured PGIE");
      }
      preprocess = make_element("nvdspreprocess", "arcface-preprocess");
      g_object_set(preprocess, "config-file", preprocess_config_path.c_str(), nullptr);
    }
    if (!sgie_config_path.empty()) {
      if (preprocess == nullptr) {
        throw std::runtime_error("ArcFace SGIE requires configured preprocessing");
      }
      sgie = make_element("nvinfer", "arcface-r50-sgie");
      g_object_set(sgie, "config-file-path", sgie_config_path.c_str(), nullptr);
      g_object_set(sgie, "input-tensor-meta", TRUE, "output-tensor-meta", TRUE, nullptr);
      g_object_set(sgie, "raw-output-generated-callback", &Impl::on_sgie_output,
                   "raw-output-generated-userdata", this, nullptr);
    }

    g_object_set(streammux, "gpu-id", gpu_id, "batch-size", batch_size, "width", 640U,
                  "height", 640U, "enable-padding", TRUE, "live-source", FALSE,
                  "batched-push-timeout", 2000, "compute-hw", 1, "nvbuf-memory-type", 2,
                  "buffer-pool-size", 64U, "async-process", TRUE, nullptr);
    g_object_set(sink, "sync", FALSE, "async", FALSE, nullptr);

    gst_bin_add_many(GST_BIN(pipeline), streammux, sink, nullptr);
    if (pgie != nullptr) {
      gst_bin_add(GST_BIN(pipeline), pgie);
    }
    if (preprocess != nullptr) {
      gst_bin_add(GST_BIN(pipeline), preprocess);
    }
    if (sgie != nullptr) {
      gst_bin_add(GST_BIN(pipeline), sgie);
    }
    source_slots.reserve(batch_size);
    for (std::uint32_t slot_index = 0; slot_index < batch_size; ++slot_index) {
      add_source_slot(slot_index);
    }
    if (pgie == nullptr) {
      require_link(gst_element_link(streammux, sink), "nvstreammux to sink");
    } else if (preprocess == nullptr) {
      require_link(gst_element_link_many(streammux, pgie, sink, nullptr),
                   "nvstreammux to PGIE to sink");
    } else if (sgie == nullptr) {
      require_link(gst_element_link_many(streammux, pgie, preprocess, sink, nullptr),
                   "nvstreammux to PGIE to preprocess to sink");
    } else {
      require_link(gst_element_link_many(streammux, pgie, preprocess, sgie, sink, nullptr),
                   "nvstreammux to PGIE to preprocess to ArcFace SGIE to sink");
    }

    GstPad *sink_pad = gst_element_get_static_pad(sink, "sink");
    if (sink_pad == nullptr) {
      throw std::runtime_error("failed to get sink pad");
    }
    sink_probe_id = gst_pad_add_probe(sink_pad, GST_PAD_PROBE_TYPE_BUFFER, &Impl::on_buffer, this,
                                       nullptr);
    gst_object_unref(sink_pad);
  }

  void add_source_slot(std::uint32_t slot_index) {
    const std::string suffix = std::to_string(slot_index);
    GstElement *source = make_element("appsrc", ("jpeg-source-" + suffix).c_str());
    GstElement *queue = make_element("queue", ("jpeg-queue-" + suffix).c_str());
    GstElement *decoder = make_element("nvjpegdec", ("jpeg-decoder-" + suffix).c_str());
    GstElement *converter =
        make_element("nvvideoconvert", ("jpeg-converter-" + suffix).c_str());
    GstElement *caps_filter = make_element("capsfilter", ("nvmm-rgba-" + suffix).c_str());

    GstCaps *jpeg_caps = gst_caps_new_empty_simple("image/jpeg");
    g_object_set(source, "caps", jpeg_caps, "format", GST_FORMAT_TIME, "is-live", FALSE,
                 "block", TRUE, "max-bytes", static_cast<guint64>(32U * 1024U * 1024U), nullptr);
    gst_caps_unref(jpeg_caps);
    g_object_set(queue, "max-size-buffers", 2U, "max-size-bytes", 0U, "max-size-time",
                 static_cast<guint64>(0), nullptr);
    g_object_set(decoder, "gpu-id", gpu_id, nullptr);
    g_object_set(converter, "gpu-id", gpu_id, "compute-hw", 1, nullptr);

    GstCaps *nvmm_caps = gst_caps_from_string("video/x-raw(memory:NVMM),format=RGBA");
    g_object_set(caps_filter, "caps", nvmm_caps, nullptr);
    gst_caps_unref(nvmm_caps);

    gst_bin_add_many(GST_BIN(pipeline), source, queue, decoder, converter, caps_filter, nullptr);
    require_link(gst_element_link_many(source, queue, decoder, converter, caps_filter, nullptr),
                 "JPEG source chain");

    const std::string pad_name = "sink_" + suffix;
    GstPad *mux_pad = gst_element_request_pad_simple(streammux, pad_name.c_str());
    GstPad *source_pad = gst_element_get_static_pad(caps_filter, "src");
    if (mux_pad == nullptr || source_pad == nullptr ||
        gst_pad_link(source_pad, mux_pad) != GST_PAD_LINK_OK) {
      if (source_pad != nullptr) {
        gst_object_unref(source_pad);
      }
      throw std::runtime_error("failed to link source slot to nvstreammux");
    }
    gst_object_unref(source_pad);
    source_slots.push_back({source, mux_pad});
  }

  void start() {
    if (started) {
      return;
    }
    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("failed to start GStreamer pipeline");
    }
    GstState state = GST_STATE_NULL;
    if (gst_element_get_state(pipeline, &state, nullptr, 10 * GST_SECOND) ==
            GST_STATE_CHANGE_FAILURE ||
        state != GST_STATE_PLAYING) {
      throw std::runtime_error("GStreamer pipeline did not reach PLAYING");
    }
    started = true;
  }

  void push_jpeg(const std::vector<std::uint8_t> &jpeg, std::uint64_t pts_token) {
    if (!started || jpeg.empty()) {
      throw std::runtime_error("pipeline is not ready for input");
    }

    GstBuffer *buffer = gst_buffer_new_allocate(nullptr, jpeg.size(), nullptr);
    if (buffer == nullptr) {
      throw std::runtime_error("failed to allocate JPEG buffer");
    }
    gst_buffer_fill(buffer, 0, jpeg.data(), jpeg.size());
    GST_BUFFER_PTS(buffer) = pts_token;
    GST_BUFFER_DTS(buffer) = GST_CLOCK_TIME_NONE;
    GST_BUFFER_DURATION(buffer) = GST_CLOCK_TIME_NONE;

    GstElement *source = source_slots[next_source_slot].appsrc;
    next_source_slot = (next_source_slot + 1) % source_slots.size();
    const GstFlowReturn result = gst_app_src_push_buffer(GST_APP_SRC(source), buffer);
    if (result != GST_FLOW_OK) {
      throw std::runtime_error("failed to push JPEG buffer");
    }
  }

  void begin_batch() { next_source_slot = 0; }

  bool wait_for_frames(std::size_t expected, std::chrono::milliseconds timeout) {
    std::unique_lock lock(frame_mutex);
    return frame_ready.wait_for(lock, timeout, [&] { return frame_count >= expected; });
  }

  std::vector<ImageDetectionResult> take_results() {
    std::lock_guard lock(frame_mutex);
    std::vector<ImageDetectionResult> available;
    available.swap(results);
    return available;
  }

  std::size_t preprocessed_face_count_value() const {
    std::lock_guard lock(frame_mutex);
    return preprocessed_faces;
  }

  void close() noexcept {
    if (pipeline == nullptr) {
      return;
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    for (auto &slot : source_slots) {
      gst_element_release_request_pad(streammux, slot.mux_sink_pad);
      gst_object_unref(slot.mux_sink_pad);
    }
    source_slots.clear();
    gst_object_unref(pipeline);
    pipeline = nullptr;
    streammux = nullptr;
    pgie = nullptr;
    preprocess = nullptr;
    sgie = nullptr;
    sink = nullptr;
    started = false;
  }

  static GstPadProbeReturn on_buffer(GstPad *, GstPadProbeInfo *info, gpointer user_data) {
    auto *self = static_cast<Impl *>(user_data);
    GstBuffer *buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    NvDsBatchMeta *batch_meta = gst_buffer_get_nvds_batch_meta(buffer);
    std::vector<ImageDetectionResult> batch_results;
    std::size_t batch_preprocessed_faces = 0;
    std::unordered_map<const NvDsObjectMeta *, std::array<float, 512>> roi_embeddings;
    {
      std::lock_guard lock(self->output_mutex);
      const auto output = self->arcface_outputs.find(buffer);
      if (output != self->arcface_outputs.end()) {
        roi_embeddings = std::move(output->second);
        self->arcface_outputs.erase(output);
      }
    }
    if (batch_meta != nullptr) {
      for (NvDsMetaList *user_item = batch_meta->batch_user_meta_list; user_item != nullptr;
           user_item = user_item->next) {
        const auto *user_meta = static_cast<const NvDsUserMeta *>(user_item->data);
        if (user_meta->base_meta.meta_type != NVDS_PREPROCESS_BATCH_META ||
            user_meta->user_meta_data == nullptr) {
          continue;
        }
        const auto *preprocess_meta =
            static_cast<const GstNvDsPreProcessBatchMeta *>(user_meta->user_meta_data);
        const auto *tensor_meta = preprocess_meta->tensor_meta;
        if (tensor_meta != nullptr && tensor_meta->raw_tensor_buffer != nullptr &&
            tensor_meta->tensor_name == "input.1" && tensor_meta->tensor_shape.size() == 4 &&
            tensor_meta->tensor_shape[1] == 3 && tensor_meta->tensor_shape[2] == 112 &&
            tensor_meta->tensor_shape[3] == 112) {
          batch_preprocessed_faces += preprocess_meta->roi_vector.size();
        }
        for (const NvDsRoiMeta &roi : preprocess_meta->roi_vector) {
          if (roi.object_meta == nullptr) {
            continue;
          }
          std::array<float, 512> embedding{};
          if (copy_arcface_embedding(roi.roi_user_meta_list, embedding)) {
            roi_embeddings.insert_or_assign(roi.object_meta, embedding);
          }
        }
      }
      batch_results.reserve(batch_meta->num_frames_in_batch);
      for (NvDsMetaList *frame_item = batch_meta->frame_meta_list; frame_item != nullptr;
           frame_item = frame_item->next) {
        const auto *frame = static_cast<const NvDsFrameMeta *>(frame_item->data);
        ImageDetectionResult result{
            frame->source_id,
            frame->buf_pts,
            frame->source_frame_width,
            frame->source_frame_height,
            {},
        };
        const float scale = std::min(
            static_cast<float>(frame->pipeline_width) / frame->source_frame_width,
            static_cast<float>(frame->pipeline_height) / frame->source_frame_height);
        const float padding_x =
            (frame->pipeline_width - frame->source_frame_width * scale) * 0.5F;
        const float padding_y =
            (frame->pipeline_height - frame->source_frame_height * scale) * 0.5F;
        result.faces.reserve(frame->num_obj_meta);
        for (NvDsMetaList *object_item = frame->obj_meta_list; object_item != nullptr;
             object_item = object_item->next) {
          const auto *object = static_cast<const NvDsObjectMeta *>(object_item->data);
          if (object->class_id != 0 || scale <= 0.0F) {
            continue;
          }
          const float left = std::clamp((object->rect_params.left - padding_x) / scale, 0.0F,
                                        static_cast<float>(result.original_width));
          const float top = std::clamp((object->rect_params.top - padding_y) / scale, 0.0F,
                                       static_cast<float>(result.original_height));
          const float right =
              std::clamp((object->rect_params.left + object->rect_params.width - padding_x) / scale,
                         0.0F, static_cast<float>(result.original_width));
          const float bottom = std::clamp(
              (object->rect_params.top + object->rect_params.height - padding_y) / scale, 0.0F,
              static_cast<float>(result.original_height));
          if (right <= left || bottom <= top || object->mask_params.data == nullptr ||
              object->mask_params.size < 15 * sizeof(float)) {
            continue;
          }

          FaceDetection detection{
              left, top, right - left, bottom - top, object->confidence, {}, {}, {}};
          for (std::size_t landmark = 0; landmark < 5; ++landmark) {
            detection.landmarks_xy[landmark * 2] = std::clamp(
                (object->mask_params.data[landmark * 3] - padding_x) / scale, 0.0F,
                static_cast<float>(result.original_width));
            detection.landmarks_xy[landmark * 2 + 1] = std::clamp(
                (object->mask_params.data[landmark * 3 + 1] - padding_y) / scale, 0.0F,
                static_cast<float>(result.original_height));
          }
          const auto embedding = roi_embeddings.find(object);
          if (embedding != roi_embeddings.end()) {
            detection.embedding = embedding->second;
          } else {
            copy_arcface_embedding(*object, detection.embedding);
          }
          copy_aligned_jpeg(*object, detection.aligned_jpeg);
          result.faces.push_back(detection);
        }
        batch_results.push_back(std::move(result));
      }
    }
    const std::size_t completed = batch_meta == nullptr ? 1 : batch_results.size();
    {
      std::lock_guard lock(self->frame_mutex);
      self->frame_count += completed;
      self->preprocessed_faces += batch_preprocessed_faces;
      self->results.insert(self->results.end(),
                           std::make_move_iterator(batch_results.begin()),
                           std::make_move_iterator(batch_results.end()));
    }
    self->frame_ready.notify_all();
    return GST_PAD_PROBE_OK;
  }

  static void on_sgie_output(GstBuffer *buffer, NvDsInferNetworkInfo *,
                             NvDsInferLayerInfo *layers, guint num_layers, guint batch_size,
                             gpointer user_data) {
    const float *output = nullptr;
    for (guint index = 0; index < num_layers; ++index) {
      if (layers[index].layerName != nullptr &&
          std::strcmp(layers[index].layerName, "output") == 0 &&
          layers[index].dataType == FLOAT && layers[index].inferDims.numElements == 512 &&
          layers[index].buffer != nullptr) {
        output = static_cast<const float *>(layers[index].buffer);
        break;
      }
    }
    NvDsBatchMeta *batch_meta = gst_buffer_get_nvds_batch_meta(buffer);
    if (output == nullptr || batch_meta == nullptr) {
      return;
    }

    std::vector<const NvDsObjectMeta *> objects;
    objects.reserve(batch_size);
    for (NvDsMetaList *item = batch_meta->batch_user_meta_list; item != nullptr;
         item = item->next) {
      const auto *user_meta = static_cast<const NvDsUserMeta *>(item->data);
      if (user_meta->base_meta.meta_type != NVDS_PREPROCESS_BATCH_META ||
          user_meta->user_meta_data == nullptr) {
        continue;
      }
      const auto *preprocess_meta =
          static_cast<const GstNvDsPreProcessBatchMeta *>(user_meta->user_meta_data);
      for (const NvDsRoiMeta &roi : preprocess_meta->roi_vector) {
        if (roi.object_meta != nullptr) {
          objects.push_back(roi.object_meta);
        }
      }
    }
    if (objects.size() != batch_size) {
      return;
    }

    std::unordered_map<const NvDsObjectMeta *, std::array<float, 512>> embeddings;
    embeddings.reserve(objects.size());
    for (std::size_t row = 0; row < objects.size(); ++row) {
      std::array<float, 512> embedding{};
      std::memcpy(embedding.data(), output + row * embedding.size(), sizeof(embedding));
      float norm_squared = 0.0F;
      for (const float value : embedding) {
        norm_squared += value * value;
      }
      const float inverse_norm = 1.0F / std::sqrt(norm_squared);
      for (float &value : embedding) {
        value *= inverse_norm;
      }
      embeddings.emplace(objects[row], embedding);
    }
    auto *self = static_cast<Impl *>(user_data);
    std::lock_guard lock(self->output_mutex);
    self->arcface_outputs.insert_or_assign(buffer, std::move(embeddings));
  }

  int gpu_id;
  std::uint32_t batch_size;
  std::string pgie_config_path;
  std::string preprocess_config_path;
  std::string sgie_config_path;
  GstElement *pipeline = nullptr;
  GstElement *streammux = nullptr;
  GstElement *pgie = nullptr;
  GstElement *preprocess = nullptr;
  GstElement *sgie = nullptr;
  GstElement *sink = nullptr;
  std::vector<SourceSlot> source_slots;
  std::size_t next_source_slot = 0;
  gulong sink_probe_id = 0;
  bool started = false;
  mutable std::mutex frame_mutex;
  std::condition_variable frame_ready;
  std::mutex output_mutex;
  std::unordered_map<GstBuffer *,
                     std::unordered_map<const NvDsObjectMeta *, std::array<float, 512>>>
      arcface_outputs;
  std::size_t frame_count = 0;
  std::size_t preprocessed_faces = 0;
  std::vector<ImageDetectionResult> results;
};

PersistentJpegPipeline::PersistentJpegPipeline(int gpu_id, std::uint32_t batch_size,
                                               std::string pgie_config_path,
                                               std::string preprocess_config_path,
                                               std::string sgie_config_path)
    : impl_(std::make_unique<Impl>(gpu_id, batch_size, std::move(pgie_config_path),
                                   std::move(preprocess_config_path),
                                   std::move(sgie_config_path))) {}

PersistentJpegPipeline::~PersistentJpegPipeline() = default;

void PersistentJpegPipeline::start() { impl_->start(); }

void PersistentJpegPipeline::begin_batch() { impl_->begin_batch(); }

void PersistentJpegPipeline::push_jpeg(const std::vector<std::uint8_t> &jpeg,
                                       std::uint64_t pts_token) {
  impl_->push_jpeg(jpeg, pts_token);
}

bool PersistentJpegPipeline::wait_for_frames(std::size_t count,
                                             std::chrono::milliseconds timeout) {
  return impl_->wait_for_frames(count, timeout);
}

std::vector<ImageDetectionResult> PersistentJpegPipeline::take_results() {
  return impl_->take_results();
}

std::size_t PersistentJpegPipeline::preprocessed_face_count() const {
  return impl_->preprocessed_face_count_value();
}

std::size_t PersistentJpegPipeline::source_slot_count() const noexcept {
  return impl_->source_slots.size();
}

void PersistentJpegPipeline::close() noexcept { impl_->close(); }

}  // namespace mvision
