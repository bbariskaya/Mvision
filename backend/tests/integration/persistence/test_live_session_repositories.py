import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import LiveSessionGeneration
from app.infrastructure.database.repositories import (
    LiveConnectorRepository,
    LiveSessionRepository,
)


@pytest.mark.asyncio
async def test_generation_snapshots_are_immutable(db_session) -> None:
    repo = LiveSessionRepository()
    session = await repo.create_session(
        db_session,
        camera_external_id="gate-1",
        location_snapshot={"site": "office-a"},
    )
    generation = await repo.create_generation(
        db_session,
        session_id=session.session_id,
        generation=1,
        requested_spec={"profile": "face-recognition-v1"},
        resolved_spec={"profileVersion": 1},
        spec_hash="a" * 64,
        profile_id="face-recognition-v1",
        profile_version=1,
        source_type="whipPush",
        source_ciphertext=None,
        ingress_path="ingress/opaque-one",
    )
    await db_session.flush()

    assert generation.generation == 1
    current = await repo.get_current_generation(db_session, session.session_id)
    assert current is not None
    assert current.generation_id == generation.generation_id
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                LiveSessionGeneration(
                    session_id=session.session_id,
                    generation=1,
                    requested_spec={},
                    resolved_spec={},
                    spec_hash="b" * 64,
                    profile_id="face-recognition-v1",
                    profile_version=1,
                    source_type="whipPush",
                    source_ciphertext=None,
                    ingress_path="ingress/opaque-other",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_reconfigure_requires_next_generation(db_session) -> None:
    repo = LiveSessionRepository()
    session = await repo.create_session(db_session, "gate-2", None)
    await repo.create_generation(
        db_session,
        session.session_id,
        1,
        {},
        {},
        "a" * 64,
        "face-recognition-v1",
        1,
        "whipPush",
        None,
        "ingress/opaque-two",
    )

    with pytest.raises(ValueError, match="LIVE_GENERATION_CONFLICT"):
        await repo.create_generation(
            db_session,
            session.session_id,
            3,
            {},
            {},
            "b" * 64,
            "face-recognition-v1",
            1,
            "whipPush",
            None,
            "ingress/opaque-three",
        )


@pytest.mark.asyncio
async def test_ready_generation_claim_retries_runtime_attempt(db_session) -> None:
    repo = LiveSessionRepository()
    session = await repo.create_session(db_session, "gate-3", None)
    generation = await repo.create_generation(
        db_session,
        session.session_id,
        1,
        {},
        {},
        "a" * 64,
        "face-recognition-v1",
        1,
        "whipPush",
        None,
        "ingress/opaque-four",
    )
    generation.media_state = "ready"
    now = datetime.datetime.now(datetime.UTC)

    first = await repo.claim_generation(db_session, "worker-0", new_uuid7(), now, lease_seconds=30)
    assert first is not None
    await repo.finish_run(
        db_session,
        first.run_id,
        "worker-0",
        first.lease_token,
        now,
        generation_id=first.generation_id,
        runtime_attempt=first.runtime_attempt,
        runtime_state="FAILED",
        error_code="TEST_RETRY",
    )
    second = await repo.claim_generation(
        db_session,
        "worker-0",
        new_uuid7(),
        now + datetime.timedelta(seconds=1),
        lease_seconds=30,
    )

    assert second is not None
    assert second.generation_id == generation.generation_id
    assert second.runtime_attempt == 2


@pytest.mark.asyncio
async def test_runtime_state_update_is_fenced_by_generation_and_attempt(db_session) -> None:
    repo = LiveSessionRepository()
    live_session = await repo.create_session(db_session, "gate-fenced", None)
    generation = await repo.create_generation(
        db_session,
        live_session.session_id,
        1,
        {},
        {},
        "c" * 64,
        "face-recognition-v1",
        1,
        "whipPush",
        None,
        "ingress/fenced",
    )
    generation.media_state = "ready"
    now = datetime.datetime.now(datetime.UTC)
    run = await repo.claim_generation(
        db_session, "worker-fenced", new_uuid7(), now, lease_seconds=30
    )
    assert run is not None

    assert not await repo.update_run_state(
        db_session,
        run.run_id,
        "worker-fenced",
        run.lease_token,
        now,
        generation_id=run.generation_id,
        runtime_attempt=run.runtime_attempt + 1,
        runtime_state="ACTIVE",
    )
    assert await repo.update_run_state(
        db_session,
        run.run_id,
        "worker-fenced",
        run.lease_token,
        now,
        generation_id=run.generation_id,
        runtime_attempt=run.runtime_attempt,
        runtime_state="ACTIVE",
    )
    await db_session.refresh(run)
    await db_session.refresh(generation)
    assert run.runtime_state == "ACTIVE"
    assert generation.runtime_state == "ACTIVE"


@pytest.mark.asyncio
async def test_reconciliation_lists_desired_generations_and_updates_media_state(
    db_session,
) -> None:
    repo = LiveSessionRepository()
    session = await repo.create_session(db_session, "gate-reconcile", None)
    generation = await repo.create_generation(
        db_session,
        session.session_id,
        1,
        {},
        {},
        "a" * 64,
        "face-recognition-v1",
        1,
        "whipPush",
        None,
        "ingress/reconcile",
    )
    stopped_session = await repo.create_session(db_session, "gate-stopped", None)
    stopped = await repo.create_generation(
        db_session,
        stopped_session.session_id,
        1,
        {},
        {},
        "b" * 64,
        "face-recognition-v1",
        1,
        "whipPush",
        None,
        "ingress/stopped",
    )
    stopped.desired_state = "stopped"
    generation.runtime_state = "FAILED"
    await db_session.flush()

    reconcilable = await repo.list_reconcilable(db_session)
    assert [item.generation_id for item in reconcilable] == [generation.generation_id]

    assert await repo.set_media_state(
        db_session,
        generation.generation_id,
        "failed",
        "LIVE_MEDIA_PATH_FAILED",
    )
    await db_session.refresh(generation)
    assert generation.media_state == "failed"
    assert generation.error_code == "LIVE_MEDIA_PATH_FAILED"

    assert await repo.set_media_state(db_session, generation.generation_id, "ready")
    await db_session.refresh(generation)
    assert generation.media_state == "ready"
    assert generation.error_code is None

    generation.error_code = "LIVE_WORKER_FAILED"
    await db_session.flush()
    assert await repo.set_media_state(db_session, generation.generation_id, "waiting")
    await db_session.refresh(generation)
    assert generation.media_state == "waiting"
    assert generation.error_code == "LIVE_WORKER_FAILED"


@pytest.mark.asyncio
async def test_connector_name_is_unique(db_session) -> None:
    repo = LiveConnectorRepository()
    await repo.create(
        db_session,
        connector_type="webhook",
        name="alerts",
        safe_config={"urlFingerprint": "abc"},
        secret_ciphertext="ciphertext",
    )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repo.create(
                db_session,
                connector_type="webhook",
                name="alerts",
                safe_config={},
                secret_ciphertext=None,
            )
