import re
from collections.abc import Mapping
from uuid import UUID

from opentelemetry.util.types import AttributeValue

SPAN_NAMES = frozenset(
    {
        "http.camera.register",
        "http.camera.start",
        "http.camera.stop",
        "live.supervisor.claim",
        "live.supervisor.lease_renew",
        "live.camera.run",
        "live.identity.resolve",
        "live.qdrant.search",
        "live.snapshot.upload",
        "live.event.commit",
        "live.notification.publish",
    }
)

NATIVE_OPERATIONS = frozenset(
    {
        "source_connect",
        "first_frame",
        "reconnect",
        "graph_rebuild",
        "inference_window",
        "output_start",
        "output_stop",
        "teardown",
    }
)

ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {
        "camera_id",
        "run_id",
        "generation",
        "protocol_version",
        "state",
        "outcome",
        "queue_type",
        "operation",
        "error_code",
        "status",
        "reason",
        "event_type",
        "dependency",
        "signal",
        "decision",
    }
)

METRIC_LABEL_KEYS = frozenset(
    {
        "decision",
        "dependency",
        "event_type",
        "operation",
        "outcome",
        "queue_type",
        "reason",
        "signal",
        "state",
        "status",
        "type",
    }
)

METRIC_LABEL_VALUES = {
    "decision": frozenset({"drop", "sample"}),
    "dependency": frozenset({"minio", "native", "postgres", "qdrant"}),
    "event_type": frozenset({"known", "unknown"}),
    "operation": NATIVE_OPERATIONS,
    "outcome": frozenset({"ambiguous", "error", "known", "success", "unknown"}),
    "queue_type": frozenset({"assignment", "identity", "native", "python"}),
    "reason": frozenset(
        {
            "backpressure",
            "cooldown",
            "low_confidence",
            "low_quality",
            "ordinary",
            "queue_full",
            "slow",
            "threshold",
        }
    ),
    "signal": frozenset({"logs", "metrics", "traces"}),
    "state": frozenset(
        {"ACTIVE", "FAILED", "RECONNECTING", "STARTING", "STOPPED", "STOPPING"}
    ),
    "status": frozenset({"cancelled", "error", "success", "timeout"}),
    "type": frozenset(
        {
            "error",
            "identity_assignment",
            "lifecycle",
            "metrics",
            "native_operation",
            "start",
            "stop",
            "track_evidence",
        }
    ),
}

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_MAX_ATTRIBUTES = 64
_MAX_STRING_LENGTH = 128
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ATTRIBUTE_ENUM_VALUES = {
    **METRIC_LABEL_VALUES,
    "operation": NATIVE_OPERATIONS | SPAN_NAMES,
    "status": METRIC_LABEL_VALUES["status"] | {"ok"},
}


def native_span_name(operation: str) -> str:
    if operation not in NATIVE_OPERATIONS:
        raise ValueError("TELEMETRY_OPERATION_NOT_ALLOWED")
    return f"live.native.{operation}"


def sanitize_attributes(values: Mapping[str, object]) -> dict[str, AttributeValue]:
    sanitized: dict[str, AttributeValue] = {}
    for key, value in values.items():
        if len(sanitized) >= _MAX_ATTRIBUTES:
            break
        if key not in ALLOWED_ATTRIBUTE_KEYS or value is None:
            continue
        if isinstance(value, bool | int | float):
            sanitized[key] = value
            continue
        if isinstance(value, str):
            text = _CONTROL_CHARACTERS.sub(" ", value)[:_MAX_STRING_LENGTH]
            if key in {"camera_id", "run_id"}:
                try:
                    text = str(UUID(text))
                except ValueError:
                    continue
            elif key == "error_code" and not _ERROR_CODE.fullmatch(text):
                continue
            elif key in _ATTRIBUTE_ENUM_VALUES and text not in _ATTRIBUTE_ENUM_VALUES[key]:
                continue
            sanitized[key] = text
    return sanitized
