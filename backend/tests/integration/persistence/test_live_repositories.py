import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import LiveDetectionEvent
from app.infrastructure.database.repositories import (
    LiveCameraRepository,
    LiveEventRepository,
    LiveRunRepository,
)

UTC = datetime.UTC


async def _camera(db_session, name: str):
    return await LiveCameraRepository().create(
        db_session,
        name=name,
        uri_ciphertext=f"ciphertext-{name}",
        uri_fingerprint=f"fingerprint-{name}",
    )


@pytest.mark.asyncio
async def test_camera_claim_creates_first_starting_generation(db_session):
    cameras = LiveCameraRepository()
    runs = LiveRunRepository()
    camera = await _camera(db_session, "north")
    await cameras.set_desired(db_session, camera.camera_id, "running")
    now = datetime.datetime.now(UTC)

    run = await runs.claim(
        db_session,
        camera.camera_id,
        "worker-0",
        new_uuid7(),
        now,
        30,
    )

    assert run is not None
    assert run.generation == 1
    assert run.runtime_state == "STARTING"
    assert run.camera_id == camera.camera_id
    assert run.lease_expires_at == now + datetime.timedelta(seconds=30)


@pytest.mark.asyncio
async def test_only_one_active_camera_can_be_desired_running(db_session):
    cameras = LiveCameraRepository()
    first = await _camera(db_session, "north")
    second = await _camera(db_session, "south")
    await cameras.set_desired(db_session, first.camera_id, "running")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await cameras.set_desired(db_session, second.camera_id, "running")


@pytest.mark.asyncio
async def test_terminal_run_is_followed_by_next_generation(db_session):
    cameras = LiveCameraRepository()
    runs = LiveRunRepository()
    camera = await _camera(db_session, "generation")
    await cameras.set_desired(db_session, camera.camera_id, "running")
    now = datetime.datetime.now(UTC)
    first_token = new_uuid7()
    first = await runs.claim(
        db_session, camera.camera_id, "worker-0", first_token, now, 30
    )
    assert first is not None

    finished = await runs.finish(
        db_session,
        first.run_id,
        "worker-0",
        first_token,
        now + datetime.timedelta(seconds=1),
        runtime_state="STOPPED",
    )
    second = await runs.claim(
        db_session,
        camera.camera_id,
        "worker-0",
        new_uuid7(),
        now + datetime.timedelta(seconds=2),
        30,
    )

    assert finished is True
    assert second is not None
    assert second.generation == 2


@pytest.mark.asyncio
async def test_stale_or_expired_lease_cannot_mutate_run(db_session):
    cameras = LiveCameraRepository()
    runs = LiveRunRepository()
    camera = await _camera(db_session, "fencing")
    await cameras.set_desired(db_session, camera.camera_id, "running")
    now = datetime.datetime.now(UTC)
    lease_token = new_uuid7()
    run = await runs.claim(
        db_session, camera.camera_id, "worker-0", lease_token, now, 30
    )
    assert run is not None

    wrong_token = await runs.update_state(
        db_session,
        run.run_id,
        "worker-0",
        new_uuid7(),
        now,
        runtime_state="ACTIVE",
        last_frame_at=now,
    )
    expired = await runs.update_metrics(
        db_session,
        run.run_id,
        "worker-0",
        lease_token,
        now + datetime.timedelta(seconds=31),
        {"frames": 10},
    )
    renewed = await runs.renew(
        db_session,
        run.run_id,
        "worker-0",
        lease_token,
        now,
        now + datetime.timedelta(seconds=60),
    )

    assert wrong_token is False
    assert expired is False
    assert renewed is True


def _event(camera_id: str, run_id: str, track_id: int, occurred_at: datetime.datetime):
    return LiveDetectionEvent(
        event_id=new_uuid7(),
        camera_id=camera_id,
        run_id=run_id,
        native_track_id=track_id,
        identity_epoch=1,
        event_type="unknown",
        face_id=None,
        name_snapshot=None,
        identity_version_snapshot=None,
        match_score=None,
        nearest_known_score=0.31,
        detector_confidence=0.91,
        first_seen_at=occurred_at - datetime.timedelta(seconds=1),
        last_seen_at=occurred_at,
        occurred_at=occurred_at,
        bounding_box={"x": 1, "y": 2, "width": 3, "height": 4},
        landmarks=[1.0] * 10,
        quality={"accepted": 3},
        snapshot_status="pending",
        snapshot_bucket=None,
        snapshot_object_key=None,
    )


async def _claimed_run(db_session, name: str):
    cameras = LiveCameraRepository()
    camera = await _camera(db_session, name)
    await cameras.set_desired(db_session, camera.camera_id, "running")
    now = datetime.datetime.now(UTC)
    run = await LiveRunRepository().claim(
        db_session, camera.camera_id, "worker-0", new_uuid7(), now, 30
    )
    assert run is not None
    return camera, run


@pytest.mark.asyncio
async def test_duplicate_track_event_returns_existing_row(db_session):
    camera, run = await _claimed_run(db_session, "event-idempotency")
    events = LiveEventRepository()
    now = datetime.datetime.now(UTC)

    first = await events.create_once(db_session, _event(camera.camera_id, run.run_id, 7, now))
    duplicate = await events.create_once(
        db_session, _event(camera.camera_id, run.run_id, 7, now)
    )

    assert duplicate.event_id == first.event_id


@pytest.mark.asyncio
async def test_event_cursor_pagination_is_deterministic(db_session):
    camera, run = await _claimed_run(db_session, "event-page")
    events = LiveEventRepository()
    now = datetime.datetime.now(UTC)
    for offset, track_id in enumerate((11, 12, 13)):
        await events.create_once(
            db_session,
            _event(
                camera.camera_id,
                run.run_id,
                track_id,
                now + datetime.timedelta(seconds=offset),
            ),
        )

    first_page = await events.list_page(db_session, camera.camera_id, limit=2)
    second_page = await events.list_page(
        db_session,
        camera.camera_id,
        limit=2,
        cursor_occurred_at=first_page[-1].occurred_at,
        cursor_event_id=first_page[-1].event_id,
    )

    assert [event.native_track_id for event in first_page] == [13, 12]
    assert [event.native_track_id for event in second_page] == [11]


@pytest.mark.asyncio
async def test_soft_deleted_camera_is_not_claimable(db_session):
    cameras = LiveCameraRepository()
    camera = await _camera(db_session, "deleted")
    await cameras.set_desired(db_session, camera.camera_id, "running")
    await cameras.soft_delete(db_session, camera.camera_id, datetime.datetime.now(UTC))

    run = await LiveRunRepository().claim(
        db_session,
        camera.camera_id,
        "worker-0",
        new_uuid7(),
        datetime.datetime.now(UTC),
        30,
    )

    assert run is None
