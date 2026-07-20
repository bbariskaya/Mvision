#include "mvision/protocol.hpp"

#include <cstdint>
#include <string>
#include <vector>

int main() {
  const mvision::ImageRequest request{
      "019b1234-1234-7123-8123-123456789abc",
      {0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9},
  };

  const auto frame = mvision::encode_request(request);
  const auto decoded = mvision::decode_request(frame);

  if (decoded.request_id != request.request_id || decoded.encoded_jpeg != request.encoded_jpeg) {
    return 1;
  }

  try {
    mvision::decode_request({0, 0, 0, 12, 1, 2});
    return 1;
  } catch (const mvision::ProtocolError &error) {
    if (std::string(error.what()) != "TRUNCATED_FRAME") {
      return 1;
    }
  }

  return 0;
}
