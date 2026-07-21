from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import msgpack

PROTOCOL_VERSION = 1
HEADER_SIZE = 4
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_ALIGNED_JPEG_BYTES = 512 * 1024
MAX_OBSERVATIONS = 10

MessageType = Literal[
    "start",
    "identity_assignment",
    "stop",
    "hello",
    "state",
    "output_ready",
    "track_evidence",
    "track_expired",
    "metrics",
    "failed",
    "stopped",
    "native_operation",
]

_TRACEPARENT_PATTERN = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)
_STABLE_ENUM_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NATIVE_OPERATIONS = {
    "source_connect",
    "first_frame",
    "reconnect",
    "graph_rebuild",
    "inference_window",
    "output_start",
    "output_stop",
    "teardown",
}
_NATIVE_ATTRIBUTE_KEYS = {
    "attempt",
    "reason",
    "state",
    "outcome",
    "batch_size",
    "object_count",
}


@dataclass(frozen=True)
class ProtocolHeader:
    protocol_version: int
    message_type: MessageType | str
    camera_id: str
    run_id: str
    generation: int
    sequence: int
    traceparent: str
    tracestate: str | None


@dataclass(frozen=True)
class StartCommand:
    header: ProtocolHeader
    uri: str
    gpu_id: int
    pgie_config_path: str
    preprocess_config_path: str
    sgie_config_path: str
    tracker_config_path: str
    output_mount_path: str
    output_udp_port: int
    latency_ms: int
    reconnect_interval_seconds: int
    reconnect_attempts: int
    frame_timeout_ns: int


@dataclass(frozen=True)
class IdentityAssignment:
    header: ProtocolHeader
    tracker_id: int
    assignment_revision: int
    identity_state: Literal["known", "unknown"]
    display_name: str | None
    face_id: str | None
    match_score: float | None
    decision_sequence: int


@dataclass(frozen=True)
class StopCommand:
    header: ProtocolHeader
    reason: str
    shutdown_deadline_ns: int


@dataclass(frozen=True)
class HelloEvent:
    header: ProtocolHeader
    build_id: str
    gstreamer_version: str
    deepstream_version: str


@dataclass(frozen=True)
class StateEvent:
    header: ProtocolHeader
    state: Literal["STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "STOPPED", "FAILED"]
    reason: str | None


@dataclass(frozen=True)
class OutputReadyEvent:
    header: ProtocolHeader
    mount_path: str
    codec: str
    caps: str


@dataclass(frozen=True)
class LiveObservation:
    timestamp_ns: int
    bbox: tuple[float, float, float, float]
    detector_confidence: float
    landmarks: tuple[float, ...]
    landmark_confidences: tuple[float, ...]
    quality_score: float
    reject_mask: int
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class TrackEvidenceEvent:
    header: ProtocolHeader
    tracker_id: int
    evidence_revision: int
    first_seen_ns: int
    last_seen_ns: int
    observations: tuple[LiveObservation, ...]
    representative_aligned_jpeg: bytes


@dataclass(frozen=True)
class TrackExpiredEvent:
    header: ProtocolHeader
    tracker_id: int
    evidence_revision: int
    first_seen_ns: int
    last_seen_ns: int
    reason: str


@dataclass(frozen=True)
class MetricsEvent:
    header: ProtocolHeader
    counters: dict[str, int]
    gauges: dict[str, float]


@dataclass(frozen=True)
class FailedEvent:
    header: ProtocolHeader
    error_code: str
    message: str


@dataclass(frozen=True)
class StoppedEvent:
    header: ProtocolHeader
    decoded_frames: int
    emitted_evidence: int
    dropped_events: int
    clean_shutdown: bool
    reason: str


@dataclass(frozen=True)
class NativeOperationEvent:
    header: ProtocolHeader
    operation: str
    started_monotonic_ns: int
    ended_monotonic_ns: int
    status: str
    error_code: str | None
    attributes: dict[str, str | int | float]


type LiveMessage = (
    StartCommand
    | IdentityAssignment
    | StopCommand
    | HelloEvent
    | StateEvent
    | OutputReadyEvent
    | TrackEvidenceEvent
    | TrackExpiredEvent
    | MetricsEvent
    | FailedEvent
    | StoppedEvent
    | NativeOperationEvent
)

_HEADER_FIELDS = {
    "protocol_version",
    "message_type",
    "camera_id",
    "run_id",
    "generation",
    "sequence",
    "traceparent",
    "tracestate",
}
_MESSAGE_FIELDS = {
    "start": {
        "uri",
        "gpu_id",
        "pgie_config_path",
        "preprocess_config_path",
        "sgie_config_path",
        "tracker_config_path",
        "output_mount_path",
        "output_udp_port",
        "latency_ms",
        "reconnect_interval_seconds",
        "reconnect_attempts",
        "frame_timeout_ns",
    },
    "identity_assignment": {
        "tracker_id",
        "assignment_revision",
        "identity_state",
        "display_name",
        "face_id",
        "match_score",
        "decision_sequence",
    },
    "stop": {"reason", "shutdown_deadline_ns"},
    "hello": {"build_id", "gstreamer_version", "deepstream_version"},
    "state": {"state", "reason"},
    "output_ready": {"mount_path", "codec", "caps"},
    "track_evidence": {
        "tracker_id",
        "evidence_revision",
        "first_seen_ns",
        "last_seen_ns",
        "observations",
        "representative_aligned_jpeg",
    },
    "track_expired": {
        "tracker_id",
        "evidence_revision",
        "first_seen_ns",
        "last_seen_ns",
        "reason",
    },
    "metrics": {"counters", "gauges"},
    "failed": {"error_code", "message"},
    "stopped": {
        "decoded_frames",
        "emitted_evidence",
        "dropped_events",
        "clean_shutdown",
        "reason",
    },
    "native_operation": {
        "operation",
        "started_monotonic_ns",
        "ended_monotonic_ns",
        "status",
        "error_code",
        "attributes",
    },
}


def validate_trace_context(traceparent: str, tracestate: str | None) -> None:
    match = _TRACEPARENT_PATTERN.fullmatch(traceparent)
    if match is None or match.group(1) == "0" * 32 or match.group(2) == "0" * 16:
        raise ValueError("INVALID_TRACE_CONTEXT")
    if tracestate is None:
        return
    try:
        encoded = tracestate.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("INVALID_TRACE_CONTEXT") from exc
    members = tracestate.split(",")
    if len(encoded) > 512 or len(members) > 32 or not members:
        raise ValueError("INVALID_TRACE_CONTEXT")
    if any(
        not member
        or "=" not in member
        or member != member.strip()
        or any(ord(character) < 0x20 or ord(character) > 0x7E for character in member)
        for member in members
    ):
        raise ValueError("INVALID_TRACE_CONTEXT")


def _integer(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("INVALID_INTEGER")
    if value < minimum:
        raise ValueError("INVALID_INTEGER")
    return value


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("NON_FINITE_VALUE")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("NON_FINITE_VALUE")
    return result


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("INVALID_UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("INVALID_UUID") from exc
    if str(parsed) != value.lower():
        raise ValueError("INVALID_UUID")
    return str(parsed)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("INVALID_PAYLOAD")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _header(payload: dict[str, object]) -> ProtocolHeader:
    version = _integer(payload["protocol_version"], minimum=1)
    if version != PROTOCOL_VERSION:
        raise ValueError("UNSUPPORTED_PROTOCOL_VERSION")
    message_type = _string(payload["message_type"])
    if message_type not in _MESSAGE_FIELDS:
        raise ValueError("UNKNOWN_MESSAGE_TYPE")
    traceparent = _string(payload["traceparent"])
    tracestate = _optional_string(payload["tracestate"])
    validate_trace_context(traceparent, tracestate)
    return ProtocolHeader(
        version,
        message_type,
        _uuid(payload["camera_id"]),
        _uuid(payload["run_id"]),
        _integer(payload["generation"], minimum=1),
        _integer(payload["sequence"]),
        traceparent,
        tracestate,
    )


def _observation_to_payload(observation: LiveObservation) -> dict[str, object]:
    return {
        "timestamp_ns": observation.timestamp_ns,
        "bbox": observation.bbox,
        "detector_confidence": observation.detector_confidence,
        "landmarks": observation.landmarks,
        "landmark_confidences": observation.landmark_confidences,
        "quality_score": observation.quality_score,
        "reject_mask": observation.reject_mask,
        "embedding": observation.embedding,
    }


def _payload(message: LiveMessage) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_version": message.header.protocol_version,
        "message_type": message.header.message_type,
        "camera_id": message.header.camera_id,
        "run_id": message.header.run_id,
        "generation": message.header.generation,
        "sequence": message.header.sequence,
        "traceparent": message.header.traceparent,
        "tracestate": message.header.tracestate,
    }
    if isinstance(message, StartCommand):
        payload.update(
            uri=message.uri,
            gpu_id=message.gpu_id,
            pgie_config_path=message.pgie_config_path,
            preprocess_config_path=message.preprocess_config_path,
            sgie_config_path=message.sgie_config_path,
            tracker_config_path=message.tracker_config_path,
            output_mount_path=message.output_mount_path,
            output_udp_port=message.output_udp_port,
            latency_ms=message.latency_ms,
            reconnect_interval_seconds=message.reconnect_interval_seconds,
            reconnect_attempts=message.reconnect_attempts,
            frame_timeout_ns=message.frame_timeout_ns,
        )
    elif isinstance(message, IdentityAssignment):
        payload.update(
            tracker_id=message.tracker_id,
            assignment_revision=message.assignment_revision,
            identity_state=message.identity_state,
            display_name=message.display_name,
            face_id=message.face_id,
            match_score=message.match_score,
            decision_sequence=message.decision_sequence,
        )
    elif isinstance(message, StopCommand):
        payload.update(reason=message.reason, shutdown_deadline_ns=message.shutdown_deadline_ns)
    elif isinstance(message, HelloEvent):
        payload.update(
            build_id=message.build_id,
            gstreamer_version=message.gstreamer_version,
            deepstream_version=message.deepstream_version,
        )
    elif isinstance(message, StateEvent):
        payload.update(state=message.state, reason=message.reason)
    elif isinstance(message, OutputReadyEvent):
        payload.update(mount_path=message.mount_path, codec=message.codec, caps=message.caps)
    elif isinstance(message, TrackEvidenceEvent):
        payload.update(
            tracker_id=message.tracker_id,
            evidence_revision=message.evidence_revision,
            first_seen_ns=message.first_seen_ns,
            last_seen_ns=message.last_seen_ns,
            observations=[_observation_to_payload(item) for item in message.observations],
            representative_aligned_jpeg=message.representative_aligned_jpeg,
        )
    elif isinstance(message, TrackExpiredEvent):
        payload.update(
            tracker_id=message.tracker_id,
            evidence_revision=message.evidence_revision,
            first_seen_ns=message.first_seen_ns,
            last_seen_ns=message.last_seen_ns,
            reason=message.reason,
        )
    elif isinstance(message, MetricsEvent):
        payload.update(counters=message.counters, gauges=message.gauges)
    elif isinstance(message, FailedEvent):
        payload.update(error_code=message.error_code, message=message.message)
    elif isinstance(message, StoppedEvent):
        payload.update(
            decoded_frames=message.decoded_frames,
            emitted_evidence=message.emitted_evidence,
            dropped_events=message.dropped_events,
            clean_shutdown=message.clean_shutdown,
            reason=message.reason,
        )
    elif isinstance(message, NativeOperationEvent):
        payload.update(
            operation=message.operation,
            started_monotonic_ns=message.started_monotonic_ns,
            ended_monotonic_ns=message.ended_monotonic_ns,
            status=message.status,
            error_code=message.error_code,
            attributes=message.attributes,
        )
    return payload


def encode_message(message: LiveMessage) -> bytes:
    packed = bytes(msgpack.packb(_payload(message), use_bin_type=True))
    if len(packed) > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    return struct.pack("!I", len(packed)) + packed


def _observation(payload: object) -> LiveObservation:
    if not isinstance(payload, dict):
        raise ValueError("INVALID_PAYLOAD")
    required = {
        "timestamp_ns",
        "bbox",
        "detector_confidence",
        "landmarks",
        "landmark_confidences",
        "quality_score",
        "reject_mask",
        "embedding",
    }
    if required - payload.keys():
        raise ValueError("MISSING_FIELD")
    if payload.keys() - required:
        raise ValueError("UNKNOWN_FIELD")
    bbox = tuple(_finite(value) for value in payload["bbox"])
    if len(bbox) != 4:
        raise ValueError("INVALID_PAYLOAD")
    landmarks = tuple(_finite(value) for value in payload["landmarks"])
    if len(landmarks) != 10:
        raise ValueError("INVALID_LANDMARKS")
    confidences = tuple(_finite(value) for value in payload["landmark_confidences"])
    if len(confidences) != 5:
        raise ValueError("INVALID_LANDMARKS")
    embedding = tuple(_finite(value) for value in payload["embedding"])
    if len(embedding) != 512:
        raise ValueError("INVALID_EMBEDDING")
    norm = math.sqrt(sum(value * value for value in embedding))
    if not 0.99 <= norm <= 1.01:
        raise ValueError("INVALID_EMBEDDING_NORM")
    return LiveObservation(
        _integer(payload["timestamp_ns"]),
        bbox,
        _finite(payload["detector_confidence"]),
        landmarks,
        confidences,
        _finite(payload["quality_score"]),
        _integer(payload["reject_mask"]),
        embedding,
    )


def _decode_payload(payload: dict[str, object]) -> LiveMessage:
    if _HEADER_FIELDS - payload.keys():
        raise ValueError("MISSING_FIELD")
    header = _header(payload)
    message_fields = _MESSAGE_FIELDS[header.message_type]
    required = _HEADER_FIELDS | message_fields
    if required - payload.keys():
        raise ValueError("MISSING_FIELD")
    if payload.keys() - required:
        raise ValueError("UNKNOWN_FIELD")

    if header.message_type == "start":
        reconnect_attempts = payload["reconnect_attempts"]
        if isinstance(reconnect_attempts, bool) or not isinstance(reconnect_attempts, int):
            raise ValueError("INVALID_INTEGER")
        if reconnect_attempts < -1:
            raise ValueError("INVALID_INTEGER")
        return StartCommand(
            header,
            _string(payload["uri"]),
            _integer(payload["gpu_id"]),
            _string(payload["pgie_config_path"]),
            _string(payload["preprocess_config_path"]),
            _string(payload["sgie_config_path"]),
            _string(payload["tracker_config_path"]),
            _string(payload["output_mount_path"]),
            _integer(payload["output_udp_port"], minimum=1),
            _integer(payload["latency_ms"]),
            _integer(payload["reconnect_interval_seconds"]),
            reconnect_attempts,
            _integer(payload["frame_timeout_ns"], minimum=1),
        )
    if header.message_type == "identity_assignment":
        identity_state = _string(payload["identity_state"])
        if identity_state not in {"known", "unknown"}:
            raise ValueError("INVALID_PAYLOAD")
        face_id = _optional_string(payload["face_id"])
        if face_id is not None:
            face_id = _uuid(face_id)
        match_score = None if payload["match_score"] is None else _finite(payload["match_score"])
        return IdentityAssignment(
            header,
            _integer(payload["tracker_id"]),
            _integer(payload["assignment_revision"], minimum=1),
            cast(Literal["known", "unknown"], identity_state),
            _optional_string(payload["display_name"]),
            face_id,
            match_score,
            _integer(payload["decision_sequence"]),
        )
    if header.message_type == "stop":
        return StopCommand(
            header,
            _string(payload["reason"]),
            _integer(payload["shutdown_deadline_ns"], minimum=1),
        )
    if header.message_type == "hello":
        return HelloEvent(
            header,
            _string(payload["build_id"]),
            _string(payload["gstreamer_version"]),
            _string(payload["deepstream_version"]),
        )
    if header.message_type == "state":
        state = _string(payload["state"])
        if state not in {"STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "STOPPED", "FAILED"}:
            raise ValueError("INVALID_PAYLOAD")
        return StateEvent(
            header,
            cast(
                Literal[
                    "STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "STOPPED", "FAILED"
                ],
                state,
            ),
            _optional_string(payload["reason"]),
        )
    if header.message_type == "output_ready":
        return OutputReadyEvent(
            header,
            _string(payload["mount_path"]),
            _string(payload["codec"]),
            _string(payload["caps"]),
        )
    if header.message_type == "track_evidence":
        observation_payloads = payload["observations"]
        if not isinstance(observation_payloads, list):
            raise ValueError("INVALID_PAYLOAD")
        observations = tuple(_observation(item) for item in observation_payloads)
        if len(observations) > MAX_OBSERVATIONS:
            raise ValueError("INVALID_PAYLOAD")
        jpeg = payload["representative_aligned_jpeg"]
        if not isinstance(jpeg, bytes):
            raise ValueError("INVALID_PAYLOAD")
        if len(jpeg) > MAX_ALIGNED_JPEG_BYTES:
            raise ValueError("SNAPSHOT_TOO_LARGE")
        return TrackEvidenceEvent(
            header,
            _integer(payload["tracker_id"]),
            _integer(payload["evidence_revision"], minimum=1),
            _integer(payload["first_seen_ns"]),
            _integer(payload["last_seen_ns"]),
            observations,
            jpeg,
        )
    if header.message_type == "track_expired":
        return TrackExpiredEvent(
            header,
            _integer(payload["tracker_id"]),
            _integer(payload["evidence_revision"], minimum=1),
            _integer(payload["first_seen_ns"]),
            _integer(payload["last_seen_ns"]),
            _string(payload["reason"]),
        )
    if header.message_type == "metrics":
        counters = payload["counters"]
        gauges = payload["gauges"]
        if not isinstance(counters, dict) or not isinstance(gauges, dict):
            raise ValueError("INVALID_PAYLOAD")
        return MetricsEvent(
            header,
            {_string(key): _integer(value) for key, value in counters.items()},
            {_string(key): _finite(value) for key, value in gauges.items()},
        )
    if header.message_type == "failed":
        return FailedEvent(
            header, _string(payload["error_code"]), _string(payload["message"])
        )
    if header.message_type == "stopped":
        if not isinstance(payload["clean_shutdown"], bool):
            raise ValueError("INVALID_PAYLOAD")
        return StoppedEvent(
            header,
            _integer(payload["decoded_frames"]),
            _integer(payload["emitted_evidence"]),
            _integer(payload["dropped_events"]),
            payload["clean_shutdown"],
            _string(payload["reason"]),
        )
    operation = _string(payload["operation"])
    status = _string(payload["status"])
    error_code = _optional_string(payload["error_code"])
    started = _integer(payload["started_monotonic_ns"])
    ended = _integer(payload["ended_monotonic_ns"])
    attributes_payload = payload["attributes"]
    if (
        operation not in _NATIVE_OPERATIONS
        or status not in {"ok", "error"}
        or ended < started
        or (status == "error" and error_code is None)
        or (status == "ok" and error_code is not None)
        or (error_code is not None and _ERROR_CODE_PATTERN.fullmatch(error_code) is None)
        or not isinstance(attributes_payload, dict)
        or len(attributes_payload) > 16
    ):
        raise ValueError("INVALID_NATIVE_OPERATION")
    attributes: dict[str, str | int | float] = {}
    for key, value in attributes_payload.items():
        if not isinstance(key, str) or key not in _NATIVE_ATTRIBUTE_KEYS or isinstance(value, bool):
            raise ValueError("INVALID_NATIVE_OPERATION")
        if isinstance(value, str):
            if _STABLE_ENUM_PATTERN.fullmatch(value) is None:
                raise ValueError("INVALID_NATIVE_OPERATION")
            attributes[key] = value
        elif isinstance(value, int):
            attributes[key] = value
        elif isinstance(value, float):
            attributes[key] = _finite(value)
        else:
            raise ValueError("INVALID_NATIVE_OPERATION")
    return NativeOperationEvent(
        header, operation, started, ended, status, error_code, attributes
    )


def decode_message(frame: bytes) -> LiveMessage:
    if len(frame) < HEADER_SIZE:
        raise ValueError("TRUNCATED_FRAME")
    payload_size = struct.unpack("!I", frame[:HEADER_SIZE])[0]
    if payload_size > MAX_FRAME_BYTES:
        raise ValueError("FRAME_TOO_LARGE")
    if len(frame) != HEADER_SIZE + payload_size:
        raise ValueError("TRUNCATED_FRAME")
    try:
        payload = msgpack.unpackb(frame[HEADER_SIZE:], raw=False)
    except (ValueError, msgpack.ExtraData, msgpack.FormatError, msgpack.StackError) as exc:
        raise ValueError("INVALID_MESSAGEPACK") from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ValueError("INVALID_PAYLOAD")
    try:
        return _decode_payload(payload)
    except KeyError as exc:
        raise ValueError("MISSING_FIELD") from exc
    except TypeError as exc:
        raise ValueError("INVALID_PAYLOAD") from exc


class DecodeContext:
    def __init__(self, camera_id: str, run_id: str, generation: int):
        self._camera_id = _uuid(camera_id)
        self._run_id = _uuid(run_id)
        self._generation = _integer(generation, minimum=1)
        self._assignment_revisions: dict[int, int] = {}

    def decode(self, frame: bytes) -> LiveMessage:
        message = decode_message(frame)
        if message.header.camera_id != self._camera_id:
            raise ValueError("WRONG_CAMERA_ID")
        if message.header.run_id != self._run_id:
            raise ValueError("WRONG_RUN_ID")
        if message.header.generation != self._generation:
            raise ValueError("WRONG_GENERATION")
        if isinstance(message, IdentityAssignment):
            previous = self._assignment_revisions.get(message.tracker_id, 0)
            if message.assignment_revision <= previous:
                raise ValueError("STALE_ASSIGNMENT_REVISION")
            self._assignment_revisions[message.tracker_id] = message.assignment_revision
        return message
