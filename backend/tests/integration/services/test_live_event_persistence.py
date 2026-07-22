import datetime
import hashlib

import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import LiveDetectionEvent
from app.infrastructure.database.repositories import (
    LiveCameraRepository,
    LiveEventRepository,
    LiveRunRepository,
)


def _event(
    camera_id: str, run_id: str, epoch: int, native_track_id: int = 42
) -> LiveDetectionEvent:
    now = datetime.datetime.now(datetime.UTC)
    return LiveDetectionEvent(
        event_id=new_uuid7(),
        camera_id=camera_id,
        run_id=run_id,
        native_track_id=native_track_id,
        identity_epoch=epoch,
        event_type="unknown",
        face_id=None,
        name_snapshot=None,
        identity_version_snapshot=None,
        match_score=None,
        nearest_known_score=0.4,
        detector_confidence=0.9,
        first_seen_at=now,
        last_seen_at=now,
        occurred_at=now,
        bounding_box={"x": 1, "y": 2, "width": 3, "height": 4},
        landmarks=[1.0] * 10,
        quality={"identity_epoch": epoch},
        snapshot_status="unavailable",
        snapshot_bucket=None,
        snapshot_object_key=None,
    )


@pytest.mark.asyncio
async def test_same_native_tracker_persists_distinct_identity_epochs(db_session) -> None:
    cameras = LiveCameraRepository()
    camera = await cameras.create(
        db_session,
        name="epoch-persistence",
        uri_ciphertext="ciphertext",
        uri_fingerprint="epoch-persistence",
    )
    await cameras.set_desired(db_session, camera.camera_id, "running")
    run = await LiveRunRepository().claim(
        db_session,
        camera.camera_id,
        "worker-0",
        new_uuid7(),
        datetime.datetime.now(datetime.UTC),
        30,
    )
    assert run is not None
    events = LiveEventRepository()

    first = await events.create_once(db_session, _event(camera.camera_id, run.run_id, 1))
    second = await events.create_once(db_session, _event(camera.camera_id, run.run_id, 2))

    assert first.event_id != second.event_id
    assert (first.identity_epoch, second.identity_epoch) == (1, 2)


@pytest.mark.asyncio
async def test_native_tracker_id_supports_full_uint64_range(db_session) -> None:
    cameras = LiveCameraRepository()
    camera = await cameras.create(
        db_session,
        name="uint64-persistence",
        uri_ciphertext="ciphertext",
        uri_fingerprint="uint64-persistence",
    )
    await cameras.set_desired(db_session, camera.camera_id, "running")
    run = await LiveRunRepository().claim(
        db_session,
        camera.camera_id,
        "worker-0",
        new_uuid7(),
        datetime.datetime.now(datetime.UTC),
        30,
    )
    assert run is not None

    persisted = await LiveEventRepository().create_once(
        db_session,
        _event(camera.camera_id, run.run_id, 1, native_track_id=(1 << 64) - 1),
    )

    assert persisted.native_track_id == (1 << 64) - 1


@pytest.mark.asyncio
async def test_live_snapshot_round_trip_preserves_bytes_and_sha(minio_adapter) -> None:
    camera_id = "019b0000-0000-7000-8000-000000000011"
    event_id = "019b0000-0000-7000-8000-000000000012"
    key = f"live/{camera_id}/{event_id}/aligned"
    sof = (
        b"\xff\xc0\x00\x11\x08\x00\x70\x00\x70"
        b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    data = b"\xff\xd8" + sof + b"\xff\xd9"

    try:
        uploaded = await minio_adapter.upload_live_snapshot(key, data, event_id)
        downloaded, stat = await minio_adapter.get_live_snapshot(key)

        assert downloaded == data
        assert uploaded.sha256 == hashlib.sha256(data).hexdigest()
        assert stat.sha256 == uploaded.sha256
        assert stat.size == len(data)
    finally:
        await minio_adapter.delete_live_snapshot(key)
