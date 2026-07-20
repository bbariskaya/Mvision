import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import FaceIdentityRepository


@pytest.mark.asyncio
async def test_create_anonymous_identity(db_session):
    repo = FaceIdentityRepository()
    face_id = new_uuid7()
    identity = await repo.create(db_session, face_id=face_id)

    assert identity.face_id == face_id
    assert identity.lifecycle_status == "anonymous"
    assert identity.name is None
    assert identity.metadata_ == {}
    assert identity.is_active is True
    assert identity.version == 1


@pytest.mark.asyncio
async def test_anonymous_identity_cannot_carry_name(db_session):
    repo = FaceIdentityRepository()

    with pytest.raises(IntegrityError):
        await repo.create(
            db_session,
            face_id=new_uuid7(),
            lifecycle_status="anonymous",
            name="Ada",
            metadata={},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_update_known_requires_name_and_increments_version(db_session):
    repo = FaceIdentityRepository()
    face_id = new_uuid7()
    await repo.create(db_session, face_id=face_id)

    updated = await repo.update_known(
        db_session,
        face_id=face_id,
        name="Ada",
        metadata={"department": "eng"},
    )

    assert updated is not None
    assert updated.lifecycle_status == "known"
    assert updated.name == "Ada"
    assert updated.metadata_ == {"department": "eng"}
    assert updated.version == 2


@pytest.mark.asyncio
async def test_known_identity_requires_non_empty_name(db_session):
    repo = FaceIdentityRepository()

    with pytest.raises(IntegrityError):
        await repo.create(
            db_session,
            face_id=new_uuid7(),
            lifecycle_status="known",
            name="",
            metadata={},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_soft_delete_keeps_record_and_increments_version(db_session):
    repo = FaceIdentityRepository()
    face_id = new_uuid7()
    await repo.create(db_session, face_id=face_id)

    deleted = await repo.soft_delete(db_session, face_id=face_id)
    fetched = await repo.get_by_id(db_session, face_id=face_id)

    assert deleted is not None
    assert deleted.is_active is False
    assert deleted.version == 2
    assert fetched is not None
    assert fetched.is_active is False


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(db_session):
    repo = FaceIdentityRepository()
    result = await repo.get_by_id(db_session, face_id=new_uuid7())
    assert result is None
