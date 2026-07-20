import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import ProcessRecordRepository


@pytest.mark.asyncio
async def test_process_record_lifecycle(db_session):
    repo = ProcessRecordRepository()
    process_id = new_uuid7()

    record = await repo.create(
        db_session,
        process_id=process_id,
        process_type="recognize",
    )
    assert record.status == "started"
    assert record.face_count == 0

    completed = await repo.complete(db_session, process_id=process_id, face_count=3)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.face_count == 3
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_process_record_fail(db_session):
    repo = ProcessRecordRepository()
    process_id = new_uuid7()

    await repo.create(db_session, process_id=process_id, process_type="enroll")
    failed = await repo.fail(db_session, process_id=process_id, error_code="STORAGE_ERROR")

    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "STORAGE_ERROR"


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    repo = ProcessRecordRepository()
    process_id = new_uuid7()
    await repo.create(db_session, process_id=process_id, process_type="recognize")

    fetched = await repo.get_by_id(db_session, process_id=process_id)
    assert fetched is not None
    assert fetched.process_id == process_id


@pytest.mark.asyncio
async def test_process_type_constraint(db_session):
    repo = ProcessRecordRepository()
    with pytest.raises(Exception):
        await repo.create(db_session, process_id=new_uuid7(), process_type="invalid")
        await db_session.flush()
