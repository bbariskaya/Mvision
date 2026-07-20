import struct
from uuid import UUID

import msgpack

from app.infrastructure.gpu.contracts import PROTOCOL_VERSION, ImageRequest


HEADER_SIZE = 4
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FRAME_BYTES = MAX_UPLOAD_BYTES + 16 * 1024 * 1024


def encode_request(request: ImageRequest) -> bytes:
    payload = msgpack.packb(
        {
            "protocol_version": request.protocol_version,
            "request_id": request.request_id,
            "encoded_jpeg": request.encoded_jpeg,
        },
        use_bin_type=True,
    )
    return struct.pack("!I", len(payload)) + payload


def decode_request(frame: bytes) -> ImageRequest:
    if len(frame) < HEADER_SIZE:
        raise ValueError("TRUNCATED_FRAME")

    payload_size = struct.unpack("!I", frame[:HEADER_SIZE])[0]
    if payload_size > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    if len(frame) - HEADER_SIZE < payload_size:
        raise ValueError("TRUNCATED_FRAME")

    payload = msgpack.unpackb(frame[HEADER_SIZE : HEADER_SIZE + payload_size], raw=False)
    if payload["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("UNSUPPORTED_PROTOCOL_VERSION")
    try:
        UUID(payload["request_id"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_REQUEST_ID") from exc
    if not isinstance(payload["encoded_jpeg"], bytes) or not payload["encoded_jpeg"].startswith(
        b"\xff\xd8"
    ):
        raise ValueError("UNSUPPORTED_MEDIA_TYPE")
    return ImageRequest(
        protocol_version=payload["protocol_version"],
        request_id=payload["request_id"],
        encoded_jpeg=payload["encoded_jpeg"],
    )
