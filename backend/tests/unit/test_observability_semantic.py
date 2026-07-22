from app.observability.semantic import (
    ALLOWED_ATTRIBUTE_KEYS,
    METRIC_LABEL_KEYS,
    SPAN_NAMES,
    native_span_name,
    sanitize_attributes,
)

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"


def test_span_names_are_fixed_semantic_operations() -> None:
    assert SPAN_NAMES == frozenset(
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
    assert native_span_name("first_frame") == "live.native.first_frame"


def test_unknown_native_operation_is_rejected() -> None:
    try:
        native_span_name("frame-42")
    except ValueError as exc:
        assert str(exc) == "TELEMETRY_OPERATION_NOT_ALLOWED"
    else:
        raise AssertionError("dynamic native span name was accepted")


def test_attributes_keep_only_allowlisted_sanitized_scalars() -> None:
    values = {
        "camera_id": CAMERA_ID,
        "run_id": RUN_ID,
        "generation": 3,
        "state": "ACTIVE",
        "outcome": "success",
        "face_id": "019b0000-0000-7000-8000-000000000003",
        "name": "Baris",
        "embedding": [1.0, 0.0],
        "uri": "rtsp://admin:secret@camera.invalid/live?token=x",
        "snapshot": b"jpeg",
        "arbitrary": "value",
    }

    assert sanitize_attributes(values) == {
        "camera_id": CAMERA_ID,
        "run_id": RUN_ID,
        "generation": 3,
        "state": "ACTIVE",
        "outcome": "success",
    }


def test_unbounded_dynamic_attribute_values_are_dropped() -> None:
    values = {
        "error_code": "LINE\nBREAK",
        "reason": "x" * 200,
        "status": None,
    }

    assert sanitize_attributes(values) == {}


def test_metric_labels_are_enum_only_and_never_identifiers() -> None:
    assert METRIC_LABEL_KEYS == frozenset(
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
    assert {"camera_id", "run_id", "track_id", "face_id", "host"}.isdisjoint(
        METRIC_LABEL_KEYS
    )
    assert {"camera_id", "run_id", "generation"}.issubset(ALLOWED_ATTRIBUTE_KEYS)
