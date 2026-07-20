import math
import struct

import msgpack
import pytest

from app.infrastructure.video.protocol import (
    HEADER_SIZE,
    VideoCompleted,
    VideoProgress,
    VideoTrackOutput,
    decode_video_event,
)


def _frame(payload: dict) -> bytes:
    packed = msgpack.packb(payload, use_bin_type=True)
    return struct.pack("!I", len(packed)) + packed


def test_decode_progress_event():
    event = decode_video_event(
        _frame(
            {
                "protocol_version": 1,
                "event_type": "progress",
                "decoded_frame": 50,
                "processed_frames": 10,
                "total_frames": 100,
                "progress_percent": 50.0,
            }
        )
    )

    assert event == VideoProgress(50, 10, 100, 50.0)


def test_decode_track_event_preserves_embedding_and_detection():
    event = decode_video_event(
        _frame(
            {
                "protocol_version": 1,
                "event_type": "track",
                "tracker_id": 42,
                "embedding": [1.0] + [0.0] * 511,
                "representative_jpeg": b"\xff\xd8x\xff\xd9",
                "detections": [
                    {
                        "frame": 5,
                        "timestamp": 0.2,
                        "x": 1.0,
                        "y": 2.0,
                        "width": 3.0,
                        "height": 4.0,
                        "detector_confidence": 0.9,
                    }
                ],
            }
        )
    )

    assert isinstance(event, VideoTrackOutput)
    assert event.tracker_id == 42
    assert len(event.embedding) == 512
    assert event.detections[0].frame == 5
    assert event.representative_jpeg.startswith(b"\xff\xd8")


def test_decode_completed_event():
    event = decode_video_event(
        _frame(
            {
                "protocol_version": 1,
                "event_type": "completed",
                "decoded_frames": 100,
                "processed_frames": 20,
                "track_count": 2,
            }
        )
    )

    assert event == VideoCompleted(100, 20, 2)


@pytest.mark.parametrize(
    "frame",
    [
        b"x" * (HEADER_SIZE - 1),
        struct.pack("!I", 100) + b"short",
        _frame({"protocol_version": 2, "event_type": "completed"}),
        _frame(
            {
                "protocol_version": 1,
                "event_type": "track",
                "tracker_id": 1,
                "embedding": [0.0],
                "representative_jpeg": b"",
                "detections": [],
            }
        ),
    ],
)
def test_decode_rejects_invalid_frames(frame):
    with pytest.raises(ValueError):
        decode_video_event(frame)


def test_decode_rejects_non_finite_values():
    frame = _frame(
        {
            "protocol_version": 1,
            "event_type": "progress",
            "decoded_frame": 1,
            "processed_frames": 1,
            "total_frames": 1,
            "progress_percent": math.nan,
        }
    )

    with pytest.raises(ValueError):
        decode_video_event(frame)
