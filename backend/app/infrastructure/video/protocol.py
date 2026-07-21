import math
import struct
from dataclasses import dataclass

import msgpack

PROTOCOL_VERSION = 1
HEADER_SIZE = 4
MAX_EVENT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class VideoDetection:
    frame: int
    timestamp: float
    x: float
    y: float
    width: float
    height: float
    detector_confidence: float
    landmarks: tuple[float, ...] = (0.0,) * 10


@dataclass(frozen=True)
class VideoProgress:
    decoded_frame: int
    processed_frames: int
    total_frames: int
    progress_percent: float


@dataclass(frozen=True)
class VideoTrackOutput:
    tracker_id: int
    embedding: tuple[float, ...]
    representative_jpeg: bytes
    detections: tuple[VideoDetection, ...]


@dataclass(frozen=True)
class VideoCompleted:
    decoded_frames: int
    processed_frames: int
    track_count: int


@dataclass(frozen=True)
class VideoFailed:
    error_code: str
    message: str


type VideoEvent = VideoProgress | VideoTrackOutput | VideoCompleted | VideoFailed


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("INVALID_NUMERIC_VALUE")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("NON_FINITE_VALUE")
    return result


def _non_negative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("INVALID_INTEGER_VALUE")
    result = int(value)
    if result < 0:
        raise ValueError("NEGATIVE_VALUE")
    return result


def decode_video_event(frame: bytes) -> VideoEvent:
    if len(frame) < HEADER_SIZE:
        raise ValueError("TRUNCATED_FRAME")
    payload_size = struct.unpack("!I", frame[:HEADER_SIZE])[0]
    if payload_size > MAX_EVENT_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    if len(frame) != HEADER_SIZE + payload_size:
        raise ValueError("TRUNCATED_FRAME")
    try:
        payload = msgpack.unpackb(frame[HEADER_SIZE:], raw=False)
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("UNSUPPORTED_PROTOCOL_VERSION")
        event_type = payload["event_type"]
        if event_type == "progress":
            progress = _finite(payload["progress_percent"])
            if progress < 0 or progress > 100:
                raise ValueError("INVALID_PROGRESS")
            return VideoProgress(
                decoded_frame=_non_negative(payload["decoded_frame"]),
                processed_frames=_non_negative(payload["processed_frames"]),
                total_frames=_non_negative(payload["total_frames"]),
                progress_percent=progress,
            )
        if event_type == "track":
            embedding = tuple(_finite(value) for value in payload["embedding"])
            if len(embedding) != 512:
                raise ValueError("INVALID_EMBEDDING")
            detections = tuple(
                VideoDetection(
                    frame=_non_negative(item["frame"]),
                    timestamp=_finite(item["timestamp"]),
                    x=_finite(item["x"]),
                    y=_finite(item["y"]),
                    width=_finite(item["width"]),
                    height=_finite(item["height"]),
                    detector_confidence=_finite(item["detector_confidence"]),
                    landmarks=tuple(_finite(value) for value in item["landmarks"]),
                )
                for item in payload["detections"]
            )
            if any(len(item.landmarks) != 10 for item in detections):
                raise ValueError("INVALID_LANDMARKS")
            return VideoTrackOutput(
                tracker_id=_non_negative(payload["tracker_id"]),
                embedding=embedding,
                representative_jpeg=bytes(payload["representative_jpeg"]),
                detections=detections,
            )
        if event_type == "completed":
            return VideoCompleted(
                decoded_frames=_non_negative(payload["decoded_frames"]),
                processed_frames=_non_negative(payload["processed_frames"]),
                track_count=_non_negative(payload["track_count"]),
            )
        if event_type == "failed":
            return VideoFailed(
                error_code=str(payload["error_code"]),
                message=str(payload["message"]),
            )
        raise ValueError("UNKNOWN_EVENT_TYPE")
    except (KeyError, TypeError, msgpack.ExtraData, msgpack.FormatError, msgpack.StackError) as exc:
        raise ValueError("INVALID_EVENT_PAYLOAD") from exc
