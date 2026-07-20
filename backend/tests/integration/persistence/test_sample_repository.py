import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
)


@pytest.mark.asyncio
async def test_sample_lifecycle(db_session):
    identity_repo = FaceIdentityRepository()
    sample_repo = FaceSampleRepository()

    face_id = new_uuid7()
    sample_id = new_uuid7()
    await identity_repo.create(db_session, face_id=face_id)
    sample = await sample_repo.create_pending(db_session, sample_id=sample_id, face_id=face_id)
    assert sample.lifecycle_state == "pending"

    updated = await sample_repo.update_blob_ready(
        db_session,
        sample_id=sample_id,
        bucket="mergenvision-faces",
        object_key=f"faces/{face_id}/{sample_id}/aligned",
        media_type="image/jpeg",
        sha256="abc123",
        detector_version="yolov8n-face-v1",
        embedding_model_version="arcface_r50_webface4m_v1",
        alignment_version="umeyama-5point-112x112",
        preprocess_version="five-point-umeyama-112x112",
        bounding_box={"x": 10, "y": 20, "width": 100, "height": 100},
    )
    assert updated is not None
    assert updated.lifecycle_state == "blob_ready"

    active = await sample_repo.set_active(db_session, sample_id=sample_id)
    assert active is not None
    assert active.lifecycle_state == "active"
    assert active.is_active is True

    samples = await sample_repo.list_by_face(db_session, face_id=face_id, active_only=True)
    assert len(samples) == 1
    assert samples[0].sample_id == sample_id


@pytest.mark.asyncio
async def test_bucket_object_key_unique(db_session):
    identity_repo = FaceIdentityRepository()
    sample_repo = FaceSampleRepository()

    face_id = new_uuid7()
    sample_id_1 = new_uuid7()
    sample_id_2 = new_uuid7()
    await identity_repo.create(db_session, face_id=face_id)
    await sample_repo.create_pending(db_session, sample_id=sample_id_1, face_id=face_id)
    await sample_repo.create_pending(db_session, sample_id=sample_id_2, face_id=face_id)

    object_key = f"faces/{face_id}/{sample_id_1}/aligned"
    await sample_repo.update_blob_ready(
        db_session,
        sample_id=sample_id_1,
        bucket="mergenvision-faces",
        object_key=object_key,
        media_type="image/jpeg",
        sha256="a" * 64,
        detector_version="v1",
        embedding_model_version="v1",
        alignment_version="v1",
        preprocess_version="v1",
        bounding_box={},
    )
    await db_session.flush()

    with pytest.raises(Exception):
        await sample_repo.update_blob_ready(
            db_session,
            sample_id=sample_id_2,
            bucket="mergenvision-faces",
            object_key=object_key,
            media_type="image/jpeg",
            sha256="b" * 64,
            detector_version="v1",
            embedding_model_version="v1",
            alignment_version="v1",
            preprocess_version="v1",
            bounding_box={},
        )
        await db_session.flush()
