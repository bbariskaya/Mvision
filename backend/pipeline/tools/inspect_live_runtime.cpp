#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include <gst/gst.h>
#include <gst/rtsp-server/rtsp-server.h>

namespace {

std::string json_string(std::string_view value) {
  std::ostringstream output;
  output << '"';
  for (const unsigned char character : value) {
    switch (character) {
      case '"':
        output << "\\\"";
        break;
      case '\\':
        output << "\\\\";
        break;
      case '\b':
        output << "\\b";
        break;
      case '\f':
        output << "\\f";
        break;
      case '\n':
        output << "\\n";
        break;
      case '\r':
        output << "\\r";
        break;
      case '\t':
        output << "\\t";
        break;
      default:
        if (character < 0x20) {
          output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<int>(character) << std::dec;
        } else {
          output << static_cast<char>(character);
        }
    }
  }
  output << '"';
  return output.str();
}

std::string gstreamer_version() {
  guint major = 0;
  guint minor = 0;
  guint micro = 0;
  guint nano = 0;
  gst_version(&major, &minor, &micro, &nano);
  std::ostringstream version;
  version << major << '.' << minor << '.' << micro;
  if (nano != 0) {
    version << '.' << nano;
  }
  return version.str();
}

std::string deepstream_version(GstElementFactory* source_factory) {
  GstPlugin* plugin = gst_plugin_feature_get_plugin(GST_PLUGIN_FEATURE(source_factory));
  if (plugin == nullptr) {
    return "unknown";
  }
  const gchar* version = gst_plugin_get_version(plugin);
  const std::string result = version == nullptr ? "unknown" : version;
  gst_object_unref(plugin);
  return result;
}

std::string default_value(GParamSpec* spec) {
  GValue value = G_VALUE_INIT;
  g_value_init(&value, G_PARAM_SPEC_VALUE_TYPE(spec));
  g_param_value_set_default(spec, &value);
  gchar* rendered = g_strdup_value_contents(&value);
  const std::string result = rendered == nullptr ? "" : rendered;
  g_free(rendered);
  g_value_unset(&value);
  return result;
}

}  // namespace

int main(int argc, char** argv) {
  gst_init(&argc, &argv);

  const std::vector<const char*> element_names{
      "nvurisrcbin", "nvvideoconvert", "nvstreammux", "nvinfer",
      "nvtracker",   "nvdspreprocess", "nvdsosd",     "nvv4l2h264enc",
      "h264parse",   "rtph264pay",     "udpsink"};
  std::vector<GstElementFactory*> factories;
  factories.reserve(element_names.size());
  bool valid = true;
  for (const char* name : element_names) {
    GstElementFactory* factory = gst_element_factory_find(name);
    factories.push_back(factory);
    if (factory == nullptr) {
      std::cerr << "missing GStreamer element factory: " << name << '\n';
      valid = false;
    }
  }

  GstElement* source = gst_element_factory_make("nvurisrcbin", nullptr);
  const std::vector<const char*> property_names{
      "uri", "latency", "drop-on-latency", "rtsp-reconnect-interval",
      "rtsp-reconnect-attempts"};
  std::vector<GParamSpec*> properties;
  properties.reserve(property_names.size());
  if (source == nullptr) {
    std::cerr << "could not construct nvurisrcbin\n";
    valid = false;
    properties.resize(property_names.size(), nullptr);
  } else {
    GObjectClass* source_class = G_OBJECT_GET_CLASS(source);
    for (const char* name : property_names) {
      GParamSpec* property = g_object_class_find_property(source_class, name);
      properties.push_back(property);
      if (property == nullptr) {
        std::cerr << "missing nvurisrcbin property: " << name << '\n';
        valid = false;
      }
    }
  }

  GstRTSPServer* server = gst_rtsp_server_new();
  const bool rtsp_server_available = server != nullptr;
  if (!rtsp_server_available) {
    std::cerr << "could not construct GstRTSPServer\n";
    valid = false;
  }

  std::cout << '{';
  std::cout << "\"gstreamerVersion\":" << json_string(gstreamer_version()) << ',';
  const std::string ds_version = factories.front() == nullptr
                                     ? "unknown"
                                     : deepstream_version(factories.front());
  std::cout << "\"deepstreamVersion\":" << json_string(ds_version) << ',';
  std::cout << "\"gstRtspServer\":"
            << (rtsp_server_available ? "true" : "false") << ',';
  std::cout << "\"elements\":{";
  for (std::size_t index = 0; index < element_names.size(); ++index) {
    if (index != 0) {
      std::cout << ',';
    }
    std::cout << json_string(element_names[index]) << ':'
              << (factories[index] == nullptr ? "false" : "true");
  }
  std::cout << "},\"nvurisrcbinProperties\":{";
  for (std::size_t index = 0; index < property_names.size(); ++index) {
    if (index != 0) {
      std::cout << ',';
    }
    std::cout << json_string(property_names[index]) << ':';
    GParamSpec* property = properties[index];
    if (property == nullptr) {
      std::cout << "null";
      continue;
    }
    std::cout << "{\"type\":"
              << json_string(g_type_name(G_PARAM_SPEC_VALUE_TYPE(property)))
              << ",\"default\":" << json_string(default_value(property))
              << ",\"readable\":"
              << ((property->flags & G_PARAM_READABLE) != 0 ? "true" : "false")
              << ",\"writable\":"
              << ((property->flags & G_PARAM_WRITABLE) != 0 ? "true" : "false")
              << '}';
  }
  std::cout << "}}\n";

  if (server != nullptr) {
    g_object_unref(server);
  }
  if (source != nullptr) {
    gst_object_unref(source);
  }
  for (GstElementFactory* factory : factories) {
    if (factory != nullptr) {
      gst_object_unref(factory);
    }
  }
  return valid ? 0 : 1;
}
