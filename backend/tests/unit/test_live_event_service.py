from types import SimpleNamespace

import pytest

from app.config import Settings
from app.infrastructure.live.protocol import ProtocolHeader, TrackExpiredEvent
from app.infrastructure.object_storage.exceptions import ObjectValidationError
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.services.face_matcher import FaceMatch
from app.services.live_event_service import LiveEventService
from app.services.live_identity_service import LiveIdentityDecision
from tests.unit.test_live_identity_service import (
    CAMERA_ID,
    RUN_ID,
    TRACEPARENT,
    _event,
)


def _header(message_type: str, sequence: int) -> ProtocolHeader:
    return ProtocolHeader(
        1, message_type, CAMERA_ID, RUN_ID, 1, sequence, TRACEPARENT, None
    )


class _Session:
    def __init__(self, commits):
        self.commits = commits

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def commit(self):
        self.commits.append(1)


class _Sessions:
    def __init__(self):
        self.commits = []

    def __call__(self):
        return _Session(self.commits)


class _Events:
    def __init__(self, *, fail=False):
        self.rows = {}
        self.fail = fail

    async def create_once(self, session, event):
        if self.fail:
            raise RuntimeError("database unavailable")
        key = (
            event.run_id,
            event.native_track_id,
            event.identity_epoch,
            event.event_type,
        )
        self.rows.setdefault(key, event)
        return self.rows[key]


class _Storage:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.uploads = []
        self.deleted = []

    async def upload_live_snapshot(self, object_key, data, event_id):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.uploads.append((object_key, data, event_id))
        return SimpleNamespace(bucket="live-test", object_key=object_key, sha256="a" * 64)

    async def delete_live_snapshot(self, object_key):
        self.deleted.append(object_key)


class _Notifier:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _known(
    face_id="019b0000-0000-7000-8000-000000000003",
    epoch=1,
    *,
    transition="known",
    reset_required=False,
):
    identity = SimpleNamespace(face_id=face_id, name="Monica", version=4)
    match = FaceMatch(identity, "sample-a", 0.91)
    return LiveIdentityDecision(
        "known",
        match,
        0.91,
        epoch,
        reset_required,
        {"recognition_threshold": 0.8, "candidate_floor": 0.7, "top_2_margin": 0.05},
        (1.0,) + (0.0,) * 511,
        transition,
        1,
    )


def _pending(epoch=1):
    return LiveIdentityDecision(
        "pending",
        None,
        0.42,
        epoch,
        False,
        {"recognition_threshold": 0.8, "candidate_floor": 0.7, "top_2_margin": 0.05},
    )


def _service(events=None, storage=None, notifier=None):
    sessions = _Sessions()
    service = LiveEventService(
        Settings(_env_file=None, minio_bucket_live="live-test"),
        events or _Events(),
        storage or _Storage(),
        notifier or _Notifier(),
        session_factory=sessions,
    )
    return service, sessions


def _jpeg(width=112, height=112):
    sof = bytes(
        [0xFF, 0xC0, 0x00, 0x11, 0x08, height >> 8, height & 0xFF, width >> 8, width & 0xFF]
    ) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    return b"\xff\xd8" + sof + b"\xff\xd9"


class _LiveClient:
    def put_object(self, bucket, key, stream, size, **kwargs):
        self.upload = (bucket, key, stream.read(), size, kwargs)

    def stat_object(self, bucket, key):
        return SimpleNamespace(
            size=len(_jpeg()),
            etag="etag",
            metadata={"X-Amz-Meta-Sha256": "a" * 64},
        )


def _storage_adapter():
    adapter = MinIOAdapter.__new__(MinIOAdapter)
    adapter._client = _LiveClient()
    adapter._live_bucket = "live-test"
    return adapter


@pytest.mark.asyncio
async def test_live_snapshot_storage_validates_shape_and_metadata() -> None:
    adapter = _storage_adapter()
    event_id = "019b0000-0000-7000-8000-000000000004"
    key = f"live/{CAMERA_ID}/{event_id}/aligned"

    info = await adapter.upload_live_snapshot(key, _jpeg(), event_id)

    assert info.bucket == "live-test"
    assert adapter._client.upload[0:4] == (
        "live-test",
        key,
        _jpeg(),
        len(_jpeg()),
    )
    assert adapter._client.upload[4]["content_type"] == "image/jpeg"
    assert adapter._client.upload[4]["metadata"]["X-Amz-Meta-Event-Id"] == event_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,data",
    [
        ("live/../../secret", _jpeg()),
        (
            f"live/{CAMERA_ID}/019b0000-0000-7000-8000-000000000004/aligned",
            _jpeg(111, 112),
        ),
        (
            f"live/{CAMERA_ID}/019b0000-0000-7000-8000-000000000004/aligned",
            b"x" * (512 * 1024 + 1),
        ),
    ],
)
async def test_live_snapshot_storage_rejects_invalid_input(key, data) -> None:
    with pytest.raises(ObjectValidationError):
        await _storage_adapter().upload_live_snapshot(
            key, data, "019b0000-0000-7000-8000-000000000004"
        )


@pytest.mark.asyncio
async def test_known_decision_persists_one_snapshot_event_and_assignment() -> None:
    events = _Events()
    storage = _Storage()
    notifier = _Notifier()
    service, sessions = _service(events, storage, notifier)
    evidence = _event((1.0, 0.0))

    assignments = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, evidence, _known()
    )
    retry = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, evidence, _known(transition="none")
    )

    assert assignments[0].identity_state == "known"
    assert assignments[0].face_id == _known().match.identity.face_id
    assert assignments[0].reference_embedding == (1.0,) + (0.0,) * 511
    assert retry == ()
    assert not hasattr(service, "_assignments")
    assert len(events.rows) == 1
    assert len(storage.uploads) == 1
    assert len(notifier.events) == 1
    assert sessions.commits


@pytest.mark.asyncio
async def test_same_face_inside_cooldown_suppresses_fragment_event() -> None:
    events = _Events()
    service, _ = _service(events)

    await service.accept_decision(CAMERA_ID, RUN_ID, 1, _event((1.0, 0.0)), _known())
    fragment = _event((1.0, 0.0))
    object.__setattr__(fragment, "tracker_id", 43)
    assignments = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, fragment, _known()
    )

    assert assignments[0].identity_state == "known"
    assert len(events.rows) == 1
    assert service.suppressed_count == 1


@pytest.mark.asyncio
async def test_new_identity_epoch_can_persist_new_known_person_on_same_tracker() -> None:
    events = _Events()
    service, _ = _service(events)

    first = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, _event((1.0, 0.0), revision=1), _known()
    )
    second = await service.accept_decision(
        CAMERA_ID,
        RUN_ID,
        1,
        _event((0.0, 1.0), revision=2),
        _known(
            "019b0000-0000-7000-8000-000000000005",
            epoch=2,
            reset_required=True,
        ),
    )

    assert first[0].identity_epoch == 1
    assert [item.identity_state for item in second] == ["unknown", "known"]
    assert second[1].identity_epoch == 2
    assert len(events.rows) == 2


@pytest.mark.asyncio
async def test_pending_unknown_is_persisted_only_after_track_expiry() -> None:
    events = _Events()
    service, _ = _service(events)
    evidence = _event((1.0, 0.0))

    assignments = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, evidence, _pending()
    )
    assert assignments == ()
    assert events.rows == {}

    expired = TrackExpiredEvent(
        _header("track_expired", 3),
        evidence.tracker_id,
        evidence.evidence_revision,
        evidence.first_seen_ns,
        evidence.last_seen_ns + 1_000_000_000,
        "idle",
    )
    final = await service.expire_track(CAMERA_ID, RUN_ID, 1, expired)

    assert final is not None
    row = next(iter(events.rows.values()))
    assert row.event_type == "unknown"
    assert row.face_id is None


@pytest.mark.asyncio
async def test_snapshot_failure_records_failed_without_false_object_key() -> None:
    events = _Events()
    service, _ = _service(events, _Storage(fail=True))

    assignments = await service.accept_decision(
        CAMERA_ID, RUN_ID, 1, _event((1.0, 0.0)), _known()
    )

    assert assignments[0].identity_state == "known"
    row = next(iter(events.rows.values()))
    assert row.snapshot_status == "failed"
    assert row.snapshot_bucket is None
    assert row.snapshot_object_key is None


@pytest.mark.asyncio
async def test_database_failure_notifies_nobody_and_returns_no_assignment() -> None:
    storage = _Storage()
    notifier = _Notifier()
    service, _ = _service(_Events(fail=True), storage, notifier)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.accept_decision(
            CAMERA_ID, RUN_ID, 1, _event((1.0, 0.0)), _known()
        )

    assert notifier.events == []
    assert len(storage.deleted) == 1


@pytest.mark.asyncio
async def test_mismatched_generation_is_rejected_before_storage_or_database() -> None:
    events = _Events()
    storage = _Storage()
    service, _ = _service(events, storage)

    with pytest.raises(ValueError, match="STALE_LIVE_EVIDENCE"):
        await service.accept_decision(
            CAMERA_ID, RUN_ID, 2, _event((1.0, 0.0)), _known()
        )

    assert storage.uploads == []
    assert events.rows == {}
