import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
)


@pytest.mark.asyncio
async def test_result_immutable_snapshot(db_session):
    identity_repo = FaceIdentityRepository()
    process_repo = ProcessRecordRepository()
    result_repo = RecognitionResultRepository()

    face_id = new_uuid7()
    process_id = new_uuid7()
    result_id = new_uuid7()
    await identity_repo.create(db_session, face_id=face_id)
    await process_repo.create(db_session, process_id=process_id, process_type="recognize")

    result = await result_repo.create(
        db_session,
        result_id=result_id,
        process_id=process_id,
        detection_ordinal=0,
        face_id=face_id,
        status_snapshot="new_anonymous",
        name_snapshot=None,
        metadata_snapshot={},
        bounding_box={"x": 0, "y": 0, "width": 1, "height": 1},
        detector_confidence=0.9,
        match_confidence=0.0,
    )

    assert result.status_snapshot == "new_anonymous"
    assert result.name_snapshot is None

    fetched = await result_repo.get_by_process(db_session, process_id=process_id)
    assert len(fetched) == 1
    assert fetched[0].result_id == result_id


@pytest.mark.asyncio
async def test_detection_ordinal_unique(db_session):
    identity_repo = FaceIdentityRepository()
    process_repo = ProcessRecordRepository()
    result_repo = RecognitionResultRepository()

    face_id = new_uuid7()
    process_id = new_uuid7()
    await identity_repo.create(db_session, face_id=face_id)
    await process_repo.create(db_session, process_id=process_id, process_type="recognize")
    await result_repo.create(
        db_session,
        result_id=new_uuid7(),
        process_id=process_id,
        detection_ordinal=0,
        face_id=face_id,
        status_snapshot="anonymous",
        name_snapshot=None,
        metadata_snapshot={},
        bounding_box={},
        detector_confidence=0.5,
        match_confidence=0.5,
    )
    await db_session.flush()

    with pytest.raises(Exception):
        await result_repo.create(
            db_session,
            result_id=new_uuid7(),
            process_id=process_id,
            detection_ordinal=0,
            face_id=face_id,
            status_snapshot="anonymous",
            name_snapshot=None,
            metadata_snapshot={},
            bounding_box={},
            detector_confidence=0.5,
            match_confidence=0.5,
        )
        await db_session.flush()
