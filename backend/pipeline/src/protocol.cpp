#include "mvision/protocol.hpp"

#include <msgpack.hpp>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace mvision {
namespace {

constexpr std::size_t kHeaderSize = 4;

std::uint32_t read_payload_size(const std::vector<std::uint8_t> &frame) {
  return (static_cast<std::uint32_t>(frame[0]) << 24U) |
         (static_cast<std::uint32_t>(frame[1]) << 16U) |
         (static_cast<std::uint32_t>(frame[2]) << 8U) |
         static_cast<std::uint32_t>(frame[3]);
}

const msgpack::object &required_field(const msgpack::object_map &map, std::string_view name) {
  for (std::uint32_t index = 0; index < map.size; ++index) {
    const auto &entry = map.ptr[index];
    if (entry.key.type == msgpack::type::STR && entry.key.as<std::string>() == name) {
      return entry.val;
    }
  }
  throw ProtocolError("INVALID_MESSAGE");
}

std::vector<std::uint8_t> frame_payload(const msgpack::sbuffer &payload) {
  if (payload.size() > kMaxFrameBytes ||
      payload.size() > std::numeric_limits<std::uint32_t>::max()) {
    throw ProtocolError("FRAME_TOO_LARGE");
  }
  const auto payload_size = static_cast<std::uint32_t>(payload.size());
  std::vector<std::uint8_t> frame(kHeaderSize + payload_size);
  frame[0] = static_cast<std::uint8_t>(payload_size >> 24U);
  frame[1] = static_cast<std::uint8_t>(payload_size >> 16U);
  frame[2] = static_cast<std::uint8_t>(payload_size >> 8U);
  frame[3] = static_cast<std::uint8_t>(payload_size);
  std::copy(payload.data(), payload.data() + payload.size(), frame.begin() + kHeaderSize);
  return frame;
}

msgpack::object_handle unpack_frame(const std::vector<std::uint8_t> &frame) {
  if (frame.size() < kHeaderSize) {
    throw ProtocolError("TRUNCATED_FRAME");
  }
  const std::uint32_t payload_size = read_payload_size(frame);
  if (payload_size > kMaxFrameBytes) {
    throw ProtocolError("FRAME_TOO_LARGE");
  }
  if (frame.size() - kHeaderSize < payload_size) {
    throw ProtocolError("TRUNCATED_FRAME");
  }
  try {
    return msgpack::unpack(reinterpret_cast<const char *>(frame.data() + kHeaderSize),
                           payload_size);
  } catch (const std::exception &) {
    throw ProtocolError("INVALID_MESSAGE");
  }
}

template <std::size_t Size>
std::array<float, Size> decode_float_array(const msgpack::object &object) {
  if (object.type != msgpack::type::ARRAY || object.via.array.size != Size) {
    throw ProtocolError("INVALID_MESSAGE");
  }
  std::array<float, Size> values{};
  for (std::size_t index = 0; index < Size; ++index) {
    values[index] = object.via.array.ptr[index].as<float>();
  }
  return values;
}

}  // namespace

std::vector<std::uint8_t> encode_request(const ImageRequest &request) {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  packer.pack_map(3);
  packer.pack("protocol_version");
  packer.pack(kProtocolVersion);
  packer.pack("request_id");
  packer.pack(request.request_id);
  packer.pack("encoded_jpeg");
  packer.pack_bin(static_cast<std::uint32_t>(request.encoded_jpeg.size()));
  packer.pack_bin_body(reinterpret_cast<const char *>(request.encoded_jpeg.data()),
                       static_cast<std::uint32_t>(request.encoded_jpeg.size()));

  return frame_payload(payload);
}

ImageRequest decode_request(const std::vector<std::uint8_t> &frame) {
  msgpack::object_handle handle = unpack_frame(frame);

  const auto &message = handle.get();
  if (message.type != msgpack::type::MAP) {
    throw ProtocolError("INVALID_MESSAGE");
  }

  const auto &map = message.via.map;
  if (required_field(map, "protocol_version").as<std::uint32_t>() != kProtocolVersion) {
    throw ProtocolError("UNSUPPORTED_PROTOCOL_VERSION");
  }

  ImageRequest request;
  request.request_id = required_field(map, "request_id").as<std::string>();
  const auto &jpeg = required_field(map, "encoded_jpeg");
  if (jpeg.type != msgpack::type::BIN) {
    throw ProtocolError("UNSUPPORTED_MEDIA_TYPE");
  }
  request.encoded_jpeg.assign(jpeg.via.bin.ptr, jpeg.via.bin.ptr + jpeg.via.bin.size);
  if (request.encoded_jpeg.size() < 2 || request.encoded_jpeg[0] != 0xff ||
      request.encoded_jpeg[1] != 0xd8) {
    throw ProtocolError("UNSUPPORTED_MEDIA_TYPE");
  }
  return request;
}

std::vector<std::uint8_t> encode_result(const ImageResult &result) {
  msgpack::sbuffer payload;
  msgpack::packer<msgpack::sbuffer> packer(payload);
  packer.pack_map(5);
  packer.pack("protocol_version");
  packer.pack(kProtocolVersion);
  packer.pack("request_id");
  packer.pack(result.request_id);
  packer.pack("status");
  packer.pack(result.status);
  packer.pack("error_code");
  packer.pack(result.error_code);
  packer.pack("faces");
  packer.pack_array(static_cast<std::uint32_t>(result.faces.size()));
  for (const FaceOutput &face : result.faces) {
    packer.pack_map(9);
    packer.pack("ordinal");
    packer.pack(face.ordinal);
    packer.pack("x");
    packer.pack(face.x);
    packer.pack("y");
    packer.pack(face.y);
    packer.pack("width");
    packer.pack(face.width);
    packer.pack("height");
    packer.pack(face.height);
    packer.pack("landmarks_xy");
    packer.pack(face.landmarks_xy);
    packer.pack("detector_confidence");
    packer.pack(face.detector_confidence);
    packer.pack("embedding");
    packer.pack(face.embedding);
    packer.pack("aligned_jpeg");
    packer.pack_bin(static_cast<std::uint32_t>(face.aligned_jpeg.size()));
    packer.pack_bin_body(reinterpret_cast<const char *>(face.aligned_jpeg.data()),
                         static_cast<std::uint32_t>(face.aligned_jpeg.size()));
  }
  return frame_payload(payload);
}

ImageResult decode_result(const std::vector<std::uint8_t> &frame) {
  msgpack::object_handle handle = unpack_frame(frame);
  const msgpack::object &message = handle.get();
  if (message.type != msgpack::type::MAP) {
    throw ProtocolError("INVALID_MESSAGE");
  }
  const msgpack::object_map &map = message.via.map;
  if (required_field(map, "protocol_version").as<std::uint32_t>() != kProtocolVersion) {
    throw ProtocolError("UNSUPPORTED_PROTOCOL_VERSION");
  }
  ImageResult result;
  result.request_id = required_field(map, "request_id").as<std::string>();
  result.status = required_field(map, "status").as<std::string>();
  result.error_code = required_field(map, "error_code").as<std::string>();
  const msgpack::object &faces = required_field(map, "faces");
  if (faces.type != msgpack::type::ARRAY) {
    throw ProtocolError("INVALID_MESSAGE");
  }
  result.faces.reserve(faces.via.array.size);
  for (std::uint32_t index = 0; index < faces.via.array.size; ++index) {
    const msgpack::object &packed_face = faces.via.array.ptr[index];
    if (packed_face.type != msgpack::type::MAP) {
      throw ProtocolError("INVALID_MESSAGE");
    }
    const msgpack::object_map &face_map = packed_face.via.map;
    FaceOutput face{};
    face.ordinal = required_field(face_map, "ordinal").as<std::uint32_t>();
    face.x = required_field(face_map, "x").as<float>();
    face.y = required_field(face_map, "y").as<float>();
    face.width = required_field(face_map, "width").as<float>();
    face.height = required_field(face_map, "height").as<float>();
    face.landmarks_xy = decode_float_array<10>(required_field(face_map, "landmarks_xy"));
    face.detector_confidence = required_field(face_map, "detector_confidence").as<float>();
    face.embedding = decode_float_array<512>(required_field(face_map, "embedding"));
    const msgpack::object &jpeg = required_field(face_map, "aligned_jpeg");
    if (jpeg.type != msgpack::type::BIN) {
      throw ProtocolError("INVALID_MESSAGE");
    }
    face.aligned_jpeg.assign(jpeg.via.bin.ptr, jpeg.via.bin.ptr + jpeg.via.bin.size);
    result.faces.push_back(std::move(face));
  }
  return result;
}

}  // namespace mvision
