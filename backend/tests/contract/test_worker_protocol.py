import struct

import pytest

from app.infrastructure.gpu.contracts import ImageRequest
from app.infrastructure.gpu.protocol import MAX_FRAME_BYTES, decode_request, encode_request


def test_image_request_round_trips_binary_jpeg_without_base64() -> None:
    request = ImageRequest(
        request_id="019b1234-1234-7123-8123-123456789abc",
        encoded_jpeg=b"\xff\xd8\xff\xe0binary-jpeg\xff\xd9",
    )

    frame = encode_request(request)

    assert struct.unpack("!I", frame[:4])[0] == len(frame) - 4
    assert decode_request(frame) == request
    assert request.encoded_jpeg in frame


def test_decode_rejects_truncated_frame() -> None:
    frame = struct.pack("!I", 12) + b"short"

    with pytest.raises(ValueError, match="TRUNCATED_FRAME"):
        decode_request(frame)


def test_decode_rejects_oversized_frame_before_reading_payload() -> None:
    frame_header = struct.pack("!I", MAX_FRAME_BYTES + 1)

    with pytest.raises(ValueError, match="FRAME_TOO_LARGE"):
        decode_request(frame_header)


def test_decode_rejects_unknown_protocol_version() -> None:
    frame = encode_request(
        ImageRequest(
            request_id="019b1234-1234-7123-8123-123456789abc",
            encoded_jpeg=b"\xff\xd8content\xff\xd9",
            protocol_version=2,
        )
    )

    with pytest.raises(ValueError, match="UNSUPPORTED_PROTOCOL_VERSION"):
        decode_request(frame)


def test_decode_rejects_invalid_request_id() -> None:
    frame = encode_request(ImageRequest(request_id="not-a-uuid", encoded_jpeg=b"\xff\xd8x\xff\xd9"))

    with pytest.raises(ValueError, match="INVALID_REQUEST_ID"):
        decode_request(frame)


def test_decode_rejects_non_jpeg_payload() -> None:
    frame = encode_request(
        ImageRequest(
            request_id="019b1234-1234-7123-8123-123456789abc",
            encoded_jpeg=b"\x89PNG\r\n\x1a\n",
        )
    )

    with pytest.raises(ValueError, match="UNSUPPORTED_MEDIA_TYPE"):
        decode_request(frame)
