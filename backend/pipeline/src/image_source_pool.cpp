#include "mvision/image_source_pool.hpp"

#include <gst/app/gstappsrc.h>
#include <gst/gst.h>
#include <gstnvdsmeta.h>

#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
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

}  // namespace

struct PersistentJpegPipeline::Impl {
  struct SourceSlot {
    GstElement *appsrc;
    GstPad *mux_sink_pad;
  };

  explicit Impl(int selected_gpu, std::uint32_t selected_batch_size)
      : gpu_id(selected_gpu), batch_size(selected_batch_size) {
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

    g_object_set(streammux, "gpu-id", gpu_id, "batch-size", batch_size, "width", 640U,
                 "height", 640U, "enable-padding", TRUE, "live-source", FALSE,
                 "batched-push-timeout", 2000, "compute-hw", 1, "nvbuf-memory-type", 2,
                 "async-process", TRUE, nullptr);
    g_object_set(sink, "sync", FALSE, "async", FALSE, nullptr);

    gst_bin_add_many(GST_BIN(pipeline), streammux, sink, nullptr);
    source_slots.reserve(batch_size);
    for (std::uint32_t slot_index = 0; slot_index < batch_size; ++slot_index) {
      add_source_slot(slot_index);
    }
    require_link(gst_element_link(streammux, sink), "nvstreammux to sink");

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

  bool wait_for_frames(std::size_t expected, std::chrono::milliseconds timeout) {
    std::unique_lock lock(frame_mutex);
    return frame_ready.wait_for(lock, timeout, [&] { return frame_count >= expected; });
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
    sink = nullptr;
    started = false;
  }

  static GstPadProbeReturn on_buffer(GstPad *, GstPadProbeInfo *info, gpointer user_data) {
    auto *self = static_cast<Impl *>(user_data);
    GstBuffer *buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    NvDsBatchMeta *batch_meta = gst_buffer_get_nvds_batch_meta(buffer);
    const std::size_t completed = batch_meta == nullptr ? 1 : batch_meta->num_frames_in_batch;
    {
      std::lock_guard lock(self->frame_mutex);
      self->frame_count += completed;
    }
    self->frame_ready.notify_all();
    return GST_PAD_PROBE_OK;
  }

  int gpu_id;
  std::uint32_t batch_size;
  GstElement *pipeline = nullptr;
  GstElement *streammux = nullptr;
  GstElement *sink = nullptr;
  std::vector<SourceSlot> source_slots;
  std::size_t next_source_slot = 0;
  gulong sink_probe_id = 0;
  bool started = false;
  std::mutex frame_mutex;
  std::condition_variable frame_ready;
  std::size_t frame_count = 0;
};

PersistentJpegPipeline::PersistentJpegPipeline(int gpu_id, std::uint32_t batch_size)
    : impl_(std::make_unique<Impl>(gpu_id, batch_size)) {}

PersistentJpegPipeline::~PersistentJpegPipeline() = default;

void PersistentJpegPipeline::start() { impl_->start(); }

void PersistentJpegPipeline::push_jpeg(const std::vector<std::uint8_t> &jpeg,
                                       std::uint64_t pts_token) {
  impl_->push_jpeg(jpeg, pts_token);
}

bool PersistentJpegPipeline::wait_for_frames(std::size_t count,
                                             std::chrono::milliseconds timeout) {
  return impl_->wait_for_frames(count, timeout);
}

std::size_t PersistentJpegPipeline::source_slot_count() const noexcept {
  return impl_->source_slots.size();
}

void PersistentJpegPipeline::close() noexcept { impl_->close(); }

}  // namespace mvision
