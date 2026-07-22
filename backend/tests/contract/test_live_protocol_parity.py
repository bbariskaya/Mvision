import os
import struct
import subprocess
from pathlib import Path

from app.infrastructure.live.protocol import (
    HelloEvent,
    IdentityAssignment,
    LiveObservation,
    NativeOperationEvent,
    ProtocolHeader,
    StartCommand,
    StopCommand,
    StoppedEvent,
    TrackEvidenceEvent,
    decode_message,
    encode_message,
)

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
FACE_ID = "019b0000-0000-7000-8000-000000000003"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACESTATE = "vendor=value"


def _header(message_type: str, sequence: int) -> ProtocolHeader:
    return ProtocolHeader(
        1, message_type, CAMERA_ID, RUN_ID, 1, sequence, TRACEPARENT, TRACESTATE
    )


def _read_frames(data: bytes):
    frames = []
    offset = 0
    while offset < len(data):
        size = struct.unpack("!I", data[offset : offset + 4])[0]
        end = offset + 4 + size
        frames.append(decode_message(data[offset:end]))
        offset = end
    return frames


def _f32(value: float) -> float:
    return struct.unpack("!f", struct.pack("!f", value))[0]


def test_python_commands_and_native_events_have_full_field_parity() -> None:
    executable = Path(
        os.getenv("MVISION_LIVE_PROTOCOL_EXECUTABLE", "build/pipeline/test_live_protocol")
    )
    commands = (
        StartCommand(
            _header("start", 1),
            "rtsp://camera.invalid/live",
            0,
            "pgie.txt",
            "preprocess.txt",
            "sgie.txt",
            "tracker.yml",
            "/live/camera",
            5400,
            8554,
            200,
            10,
            -1,
            5_000_000_000,
        ),
        IdentityAssignment(
            _header("identity_assignment", 2),
            42,
            3,
            1,
            "known",
            "Ada",
            FACE_ID,
            0.87,
            0.8,
            (1.0,) + (0.0,) * 511,
            12,
        ),
        StopCommand(_header("stop", 3), "operator", 2_000_000_000),
    )

    result = subprocess.run(
        [str(executable), "--parity"],
        input=b"".join(encode_message(command) for command in commands),
        capture_output=True,
        check=True,
    )

    observation = LiveObservation(
        1_000_000_000,
        (10.0, 20.0, 100.0, 120.0),
        _f32(0.91),
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
        tuple(_f32(value) for value in (0.9, 0.8, 0.7, 0.6, 0.5)),
        _f32(0.72),
        0,
        (1.0,) + (0.0,) * 511,
    )
    expected = [
        HelloEvent(_header("hello", 101), "parity-build", "1.24.2", "9.0.0"),
        TrackEvidenceEvent(
            _header("track_evidence", 102),
            42,
            3,
            1_000_000_000,
            2_000_000_000,
            (observation,),
            b"\xff\xd8\xff\xd9",
        ),
        NativeOperationEvent(
            _header("native_operation", 103),
            "first_frame",
            1_000_000_000,
            1_100_000_000,
            "ok",
            None,
            {"object_count": 1, "outcome": "active"},
        ),
        StoppedEvent(_header("stopped", 104), 20, 1, 0, True, "operator"),
    ]
    assert _read_frames(result.stdout) == expected
    assert result.stderr == b""
