import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
)


@pytest.mark.asyncio
async def test_event_logging(db_session):
    identity_repo = FaceIdentityRepository()
    process_repo = ProcessRecordRepository()
    event_repo = ProcessEventRepository()

    face_id = new_uuid7()
    process_id = new_uuid7()
    await identity_repo.create(db_session, face_id=face_id)
    await process_repo.create(db_session, process_id=process_id, process_type="recognize")

    event = await event_repo.create(
        db_session,
        process_id=process_id,
        event_type="sample_uploaded",
        sanitized_details={"sample_id": new_uuid7(), "stage": "blob_ready"},
    )

    assert event.process_id == process_id
    assert event.event_type == "sample_uploaded"
    assert "sample_id" in event.sanitized_details

    events = await event_repo.get_by_process(db_session, process_id=process_id)
    assert len(events) == 1
    assert events[0].event_id == event.event_id
