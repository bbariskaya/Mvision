#include "mvision/protocol.hpp"

#include <array>
#include <cmath>
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

  std::array<float, 512> embedding{};
  embedding[0] = 1.0F;
  const mvision::ImageResult image_result{
      request.request_id,
      "OK",
      "",
      {{0, 10.0F, 20.0F, 30.0F, 40.0F,
        {1.0F, 2.0F, 3.0F, 4.0F, 5.0F, 6.0F, 7.0F, 8.0F, 9.0F, 10.0F},
        0.95F, embedding, {0xff, 0xd8, 0xff, 0xd9}}},
  };
  const auto result_frame = mvision::encode_result(image_result);
  const auto decoded_result = mvision::decode_result(result_frame);
  if (decoded_result.request_id != image_result.request_id ||
      decoded_result.status != image_result.status ||
      decoded_result.error_code != image_result.error_code || decoded_result.faces.size() != 1 ||
      decoded_result.faces[0].embedding != embedding ||
      decoded_result.faces[0].aligned_jpeg != image_result.faces[0].aligned_jpeg ||
      std::abs(decoded_result.faces[0].detector_confidence - 0.95F) > 1.0e-6F) {
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
