import struct
from uuid import UUID

import msgpack

from app.infrastructure.gpu.contracts import (
    PROTOCOL_VERSION,
    FaceDetection,
    ImageRequest,
    ImageResult,
)

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
    return bytes(struct.pack("!I", len(payload)) + payload)


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


def decode_result(frame: bytes) -> ImageResult:
    if len(frame) < HEADER_SIZE:
        raise ValueError("TRUNCATED_FRAME")
    payload_size = struct.unpack("!I", frame[:HEADER_SIZE])[0]
    if payload_size > MAX_FRAME_BYTES or len(frame) - HEADER_SIZE < payload_size:
        raise ValueError("INVALID_RESULT_FRAME")
    payload = msgpack.unpackb(frame[HEADER_SIZE : HEADER_SIZE + payload_size], raw=False)
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("UNSUPPORTED_PROTOCOL_VERSION")
    try:
        UUID(payload["request_id"])
        faces = tuple(
            FaceDetection(
                ordinal=int(face["ordinal"]),
                x=float(face["x"]),
                y=float(face["y"]),
                width=float(face["width"]),
                height=float(face["height"]),
                landmarks_xy=tuple(float(value) for value in face["landmarks_xy"]),
                detector_confidence=float(face["detector_confidence"]),
                embedding=tuple(float(value) for value in face["embedding"]),
                aligned_jpeg=bytes(face["aligned_jpeg"]),
            )
            for face in payload["faces"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("INVALID_RESULT_PAYLOAD") from exc
    return ImageResult(
        request_id=payload["request_id"],
        status=str(payload["status"]),
        error_code=str(payload["error_code"]),
        faces=faces,
    )
