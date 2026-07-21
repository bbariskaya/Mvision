#include <array>
#include <iostream>

#include <gst/gst.h>
#include <gst/rtsp-server/rtsp-server.h>

namespace {

bool require_element_factory(const char* name) {
  GstElementFactory* factory = gst_element_factory_find(name);
  if (factory == nullptr) {
    std::cerr << "missing GStreamer element factory: " << name << '\n';
    return false;
  }
  gst_object_unref(factory);
  return true;
}

bool require_property(GObjectClass* object_class, const char* name) {
  if (g_object_class_find_property(object_class, name) == nullptr) {
    std::cerr << "missing nvurisrcbin property: " << name << '\n';
    return false;
  }
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  gst_init(&argc, &argv);

  constexpr std::array required{
      "nvurisrcbin", "nvvideoconvert", "nvstreammux", "nvinfer",
      "nvtracker",   "nvdspreprocess", "nvdsosd",     "nvv4l2h264enc",
      "h264parse",   "rtph264pay",     "udpsink"};
  bool valid = true;
  for (const char* name : required) {
    valid = require_element_factory(name) && valid;
  }

  GstElement* source = gst_element_factory_make("nvurisrcbin", nullptr);
  if (source == nullptr) {
    std::cerr << "could not construct nvurisrcbin\n";
    valid = false;
  } else {
    constexpr std::array source_properties{
        "uri", "latency", "drop-on-latency", "rtsp-reconnect-interval",
        "rtsp-reconnect-attempts"};
    GObjectClass* source_class = G_OBJECT_GET_CLASS(source);
    for (const char* name : source_properties) {
      valid = require_property(source_class, name) && valid;
    }
    gst_object_unref(source);
  }

  GstRTSPServer* server = gst_rtsp_server_new();
  if (server == nullptr) {
    std::cerr << "could not construct GstRTSPServer\n";
    valid = false;
  } else {
    g_object_unref(server);
  }

  return valid ? 0 : 1;
}
