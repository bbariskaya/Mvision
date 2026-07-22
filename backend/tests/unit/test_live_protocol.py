import math
import struct
from dataclasses import replace

import msgpack
import pytest

from app.infrastructure.live.protocol import (
    MAX_FRAME_BYTES,
    DecodeContext,
    FailedEvent,
    HelloEvent,
    IdentityAssignment,
    LiveObservation,
    MetricsEvent,
    NativeOperationEvent,
    OutputReadyEvent,
    ProtocolHeader,
    StartCommand,
    StateEvent,
    StopCommand,
    StoppedEvent,
    TrackEvidenceEvent,
    TrackExpiredEvent,
    decode_message,
    encode_message,
)

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACESTATE = "vendor=value"


def _header(message_type: str, *, sequence: int = 7) -> ProtocolHeader:
    return ProtocolHeader(
        1, message_type, CAMERA_ID, RUN_ID, 1, sequence, TRACEPARENT, TRACESTATE
    )


def _observation() -> LiveObservation:
    return LiveObservation(
        timestamp_ns=1_000_000_000,
        bbox=(10.0, 20.0, 100.0, 120.0),
        detector_confidence=0.91,
        landmarks=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
        landmark_confidences=(0.9, 0.8, 0.7, 0.6, 0.5),
        quality_score=0.72,
        reject_mask=0,
        embedding=(1.0,) + (0.0,) * 511,
    )


def _messages():
    return (
        StartCommand(
            _header("start"),
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
            _header("identity_assignment", sequence=8),
            42,
            3,
            1,
            "known",
            "Ada",
            "019b0000-0000-7000-8000-000000000003",
            0.87,
            0.8,
            (1.0,) + (0.0,) * 511,
            12,
        ),
        StopCommand(_header("stop", sequence=9), "operator", 2_000_000_000),
        HelloEvent(_header("hello"), "build-1", "1.24.2", "9.0.0"),
        StateEvent(_header("state"), "ACTIVE", "first_frame"),
        OutputReadyEvent(
            _header("output_ready"),
            "/live/camera",
            "H264",
            "video/x-h264,stream-format=byte-stream",
        ),
        TrackEvidenceEvent(
            _header("track_evidence"),
            42,
            2,
            1_000_000_000,
            2_000_000_000,
            (_observation(),),
            b"\xff\xd8\xff\xd9",
        ),
        TrackExpiredEvent(
            _header("track_expired"), 42, 2, 1_000_000_000, 2_000_000_000, "idle"
        ),
        MetricsEvent(_header("metrics"), {"decoded_frames": 20}, {"fps": 29.97}),
        FailedEvent(_header("failed"), "LIVE_PIPELINE_ERROR", "pipeline failed"),
        StoppedEvent(_header("stopped"), 20, 2, 0, True, "operator"),
        NativeOperationEvent(
            _header("native_operation"),
            "reconnect",
            1_000_000_000,
            1_200_000_000,
            "ok",
            None,
            {"attempt": 2, "outcome": "recovered"},
        ),
    )


@pytest.mark.parametrize("message", _messages())
def test_round_trip_preserves_every_message(message) -> None:
    assert decode_message(encode_message(message)) == message


def _payload(message) -> dict:
    frame = encode_message(message)
    return msgpack.unpackb(frame[4:], raw=False)


def _frame(payload: dict) -> bytes:
    packed = msgpack.packb(payload, use_bin_type=True)
    return struct.pack("!I", len(packed)) + packed


@pytest.mark.parametrize("frame", [b"", b"\x00\x00\x00", b"\x00\x00\x00\x08abc"])
def test_rejects_truncated_header_or_body(frame: bytes) -> None:
    with pytest.raises(ValueError, match="^TRUNCATED_FRAME$"):
        decode_message(frame)


def test_rejects_payload_over_four_mib_before_reading_body() -> None:
    with pytest.raises(ValueError, match="^FRAME_TOO_LARGE$"):
        decode_message(struct.pack("!I", MAX_FRAME_BYTES + 1))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("protocol_version", 2, "UNSUPPORTED_PROTOCOL_VERSION"),
        ("message_type", "future", "UNKNOWN_MESSAGE_TYPE"),
        ("camera_id", "not-a-uuid", "INVALID_UUID"),
        ("generation", True, "INVALID_INTEGER"),
    ],
)
def test_rejects_invalid_header_fields(field: str, value: object, code: str) -> None:
    payload = _payload(StateEvent(_header("state"), "ACTIVE", None))
    payload[field] = value

    with pytest.raises(ValueError, match=f"^{code}$"):
        decode_message(_frame(payload))


def test_context_rejects_wrong_generation() -> None:
    context = DecodeContext(CAMERA_ID, RUN_ID, 2)

    with pytest.raises(ValueError, match="^WRONG_GENERATION$"):
        context.decode(encode_message(StateEvent(_header("state"), "ACTIVE", None)))


@pytest.mark.parametrize(
    ("camera_id", "run_id", "code"),
    [
        ("019b0000-0000-7000-8000-000000000009", RUN_ID, "WRONG_CAMERA_ID"),
        (CAMERA_ID, "019b0000-0000-7000-8000-000000000009", "WRONG_RUN_ID"),
    ],
)
def test_context_rejects_wrong_camera_or_run(camera_id: str, run_id: str, code: str) -> None:
    context = DecodeContext(camera_id, run_id, 1)

    with pytest.raises(ValueError, match=f"^{code}$"):
        context.decode(encode_message(StateEvent(_header("state"), "ACTIVE", None)))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload.pop("state"), "MISSING_FIELD"),
        (lambda payload: payload.__setitem__("future", 1), "UNKNOWN_FIELD"),
    ],
)
def test_rejects_missing_or_unknown_fields(mutation, code: str) -> None:
    payload = _payload(StateEvent(_header("state"), "ACTIVE", None))
    mutation(payload)

    with pytest.raises(ValueError, match=f"^{code}$"):
        decode_message(_frame(payload))


def test_rejects_non_finite_metric() -> None:
    payload = _payload(MetricsEvent(_header("metrics"), {}, {"fps": 1.0}))
    payload["gauges"]["fps"] = math.nan

    with pytest.raises(ValueError, match="^NON_FINITE_VALUE$"):
        decode_message(_frame(payload))


@pytest.mark.parametrize(
    ("embedding", "code"),
    [
        ((1.0,) + (0.0,) * 510, "INVALID_EMBEDDING"),
        ((0.5,) + (0.0,) * 511, "INVALID_EMBEDDING_NORM"),
        ((math.inf,) + (0.0,) * 511, "NON_FINITE_VALUE"),
    ],
)
def test_rejects_invalid_embedding(embedding: tuple[float, ...], code: str) -> None:
    evidence = replace(_messages()[6], observations=(replace(_observation(), embedding=embedding),))

    with pytest.raises(ValueError, match=f"^{code}$"):
        decode_message(encode_message(evidence))


def test_rejects_landmarks_not_exactly_ten_coordinates() -> None:
    observation = replace(_observation(), landmarks=(1.0,) * 9)
    evidence = replace(_messages()[6], observations=(observation,))

    with pytest.raises(ValueError, match="^INVALID_LANDMARKS$"):
        decode_message(encode_message(evidence))


def test_rejects_snapshot_over_512_kib() -> None:
    evidence = replace(_messages()[6], representative_aligned_jpeg=b"x" * (512 * 1024 + 1))

    with pytest.raises(ValueError, match="^SNAPSHOT_TOO_LARGE$"):
        decode_message(encode_message(evidence))


def test_rejects_out_of_order_assignment_revision() -> None:
    context = DecodeContext(CAMERA_ID, RUN_ID, 1)
    assignment = _messages()[1]
    context.decode(encode_message(assignment))

    with pytest.raises(ValueError, match="^STALE_ASSIGNMENT_REVISION$"):
        context.decode(encode_message(assignment))


@pytest.mark.parametrize(
    ("state", "reference", "code"),
    [
        ("known", None, "INVALID_IDENTITY_ASSIGNMENT"),
        ("known", (1.0,) + (0.0,) * 510, "INVALID_EMBEDDING"),
        ("known", (math.nan,) + (0.0,) * 511, "NON_FINITE_VALUE"),
        ("unknown", (1.0,) + (0.0,) * 511, "INVALID_IDENTITY_ASSIGNMENT"),
    ],
)
def test_assignment_requires_valid_reference_embedding(
    state: str, reference: tuple[float, ...] | None, code: str
) -> None:
    payload = _payload(_messages()[1])
    payload["identity_state"] = state
    payload["reference_embedding"] = reference
    if state == "unknown":
        payload["display_name"] = None
        payload["face_id"] = None
        payload["match_score"] = None
        payload["recognition_threshold"] = None

    with pytest.raises(ValueError, match=f"^{code}$"):
        decode_message(_frame(payload))


@pytest.mark.parametrize(
    "traceparent",
    [
        "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01",
        "00-4bf92f35-00f067aa0ba902b7-01",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
        "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-zz",
    ],
)
def test_rejects_invalid_traceparent(traceparent: str) -> None:
    payload = _payload(StateEvent(_header("state"), "ACTIVE", None))
    payload["traceparent"] = traceparent

    with pytest.raises(ValueError, match="^INVALID_TRACE_CONTEXT$"):
        decode_message(_frame(payload))


@pytest.mark.parametrize(
    "tracestate",
    ["x" * 513, ",".join(f"v{index}=x" for index in range(33))],
)
def test_rejects_oversized_tracestate(tracestate: str) -> None:
    payload = _payload(StateEvent(_header("state"), "ACTIVE", None))
    payload["tracestate"] = tracestate

    with pytest.raises(ValueError, match="^INVALID_TRACE_CONTEXT$"):
        decode_message(_frame(payload))


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"operation": "future"}, "INVALID_NATIVE_OPERATION"),
        ({"status": "future"}, "INVALID_NATIVE_OPERATION"),
        ({"started_monotonic_ns": 3, "ended_monotonic_ns": 2}, "INVALID_NATIVE_OPERATION"),
        ({"status": "error", "error_code": None}, "INVALID_NATIVE_OPERATION"),
        (
            {"attributes": {f"attempt{index}": index for index in range(17)}},
            "INVALID_NATIVE_OPERATION",
        ),
        ({"attributes": {"uri": "secret"}}, "INVALID_NATIVE_OPERATION"),
        ({"attributes": {"attempt": math.nan}}, "NON_FINITE_VALUE"),
        ({"attributes": {"attempt": True}}, "INVALID_NATIVE_OPERATION"),
    ],
)
def test_rejects_invalid_native_operation(changes: dict, code: str) -> None:
    event = _messages()[-1]
    invalid = replace(event, **changes)

    with pytest.raises(ValueError, match=f"^{code}$"):
        decode_message(encode_message(invalid))
