#include "mvision/protocol.hpp"

#include <msgpack.hpp>

#include <algorithm>
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

ImageRequest decode_request(const std::vector<std::uint8_t> &frame) {
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

  msgpack::object_handle handle;
  try {
    handle = msgpack::unpack(reinterpret_cast<const char *>(frame.data() + kHeaderSize),
                             payload_size);
  } catch (const std::exception &) {
    throw ProtocolError("INVALID_MESSAGE");
  }

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

}  // namespace mvision
