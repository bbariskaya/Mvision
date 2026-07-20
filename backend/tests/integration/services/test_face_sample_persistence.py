import pytest

from app.config import get_settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.exceptions import ObjectStorageError
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.exceptions import VectorStoreError
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services import FaceSamplePersistenceService
from app.services.exceptions import StorageError
from app.services.exceptions import VectorStoreError as VecErr
from tests.integration.helpers import normalized_vector


def make_service(minio, qdrant):
    return FaceSamplePersistenceService(
        settings=get_settings(),
        identity_repo=FaceIdentityRepository(),
        sample_repo=FaceSampleRepository(),
        process_repo=ProcessRecordRepository(),
        event_repo=ProcessEventRepository(),
        minio=minio,
        qdrant=qdrant,
    )


async def cleanup(face_id: str, sample_id: str, process_id: str, object_key: str) -> None:
    async with AsyncSessionLocal() as session:
        sample = await FaceSampleRepository().get_by_id(session, sample_id=sample_id)
        if sample:
            await session.delete(sample)
        identity = await FaceIdentityRepository().get_by_id(session, face_id=face_id)
        if identity:
            await session.delete(identity)
        process = await ProcessRecordRepository().get_by_id(session, process_id=process_id)
        if process:
            await session.delete(process)
        await session.commit()
    try:
        await MinIOAdapter(get_settings()).delete_aligned_sample(object_key)
    except Exception:
        pass
    try:
        await QdrantAdapter(get_settings()).delete(sample_id)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_happy_path_persist(minio_adapter, qdrant_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id = new_uuid7()
    object_key = f"faces/{face_id}/{sample_id}/aligned"
    service = make_service(minio_adapter, qdrant_adapter)

    sample = await service.persist(
        process_id=process_id,
        face_id=face_id,
        sample_id=sample_id,
        aligned_bytes=b"aligned-bytes",
        media_type="image/jpeg",
        vector=normalized_vector(),
        bounding_box={"x": 0, "y": 0, "width": 1, "height": 1},
        detector_version="yolov8n-face-v1",
        embedding_model_version="arcface_r50_webface4m_v1",
        alignment_version="umeyama-5point-112x112",
        preprocess_version="five-point-umeyama-112x112",
    )

    assert sample.lifecycle_state == "active"
    assert sample.is_active is True
    assert sample.object_key == object_key

    async with AsyncSessionLocal() as session:
        process = await ProcessRecordRepository().get_by_id(session, process_id=process_id)
        assert process.status == "completed"
        events = await ProcessEventRepository().get_by_process(session, process_id=process_id)
        assert len(events) >= 2

    await cleanup(face_id, sample_id, process_id, object_key)


@pytest.mark.asyncio
async def test_minio_failure_marks_sample_failed(qdrant_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id = new_uuid7()

    class FailingMinIOAdapter(MinIOAdapter):
        async def upload_aligned_sample(self, *args, **kwargs):
            raise ObjectStorageError("upload failed")

    service = make_service(FailingMinIOAdapter(get_settings()), qdrant_adapter)

    with pytest.raises(StorageError):
        await service.persist(
            process_id=process_id,
            face_id=face_id,
            sample_id=sample_id,
            aligned_bytes=b"aligned-bytes",
            media_type="image/jpeg",
            vector=normalized_vector(),
            bounding_box={},
        )

    async with AsyncSessionLocal() as session:
        sample = await FaceSampleRepository().get_by_id(session, sample_id=sample_id)
        assert sample.lifecycle_state == "failed"
        process = await ProcessRecordRepository().get_by_id(session, process_id=process_id)
        assert process.status == "failed"

    await cleanup(face_id, sample_id, process_id, f"faces/{face_id}/{sample_id}/aligned")


@pytest.mark.asyncio
async def test_qdrant_failure_after_minio_marks_failed(minio_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id = new_uuid7()

    class FailingQdrantAdapter(QdrantAdapter):
        async def upsert(self, *args, **kwargs):
            raise VectorStoreError("upsert failed")

    service = make_service(minio_adapter, FailingQdrantAdapter(get_settings()))

    with pytest.raises(VecErr):
        await service.persist(
            process_id=process_id,
            face_id=face_id,
            sample_id=sample_id,
            aligned_bytes=b"aligned-bytes",
            media_type="image/jpeg",
            vector=normalized_vector(),
            bounding_box={},
        )

    async with AsyncSessionLocal() as session:
        sample = await FaceSampleRepository().get_by_id(session, sample_id=sample_id)
        assert sample.lifecycle_state == "failed"
        process = await ProcessRecordRepository().get_by_id(session, process_id=process_id)
        assert process.status == "failed"

    await cleanup(face_id, sample_id, process_id, f"faces/{face_id}/{sample_id}/aligned")


@pytest.mark.asyncio
async def test_retry_after_minio_failure(minio_adapter, qdrant_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id_1 = new_uuid7()

    class FailingMinIOAdapter(MinIOAdapter):
        async def upload_aligned_sample(self, *args, **kwargs):
            raise ObjectStorageError("upload failed")

    failing_service = make_service(FailingMinIOAdapter(get_settings()), qdrant_adapter)
    with pytest.raises(StorageError):
        await failing_service.persist(
            process_id=process_id_1,
            face_id=face_id,
            sample_id=sample_id,
            aligned_bytes=b"aligned-bytes",
            media_type="image/jpeg",
            vector=normalized_vector(),
            bounding_box={},
        )

    process_id_2 = new_uuid7()
    real_service = make_service(minio_adapter, qdrant_adapter)
    sample = await real_service.persist(
        process_id=process_id_2,
        face_id=face_id,
        sample_id=sample_id,
        aligned_bytes=b"aligned-bytes",
        media_type="image/jpeg",
        vector=normalized_vector(),
        bounding_box={},
    )

    assert sample.lifecycle_state == "active"

    await cleanup(face_id, sample_id, process_id_2, f"faces/{face_id}/{sample_id}/aligned")


@pytest.mark.asyncio
async def test_retry_idempotent_active(minio_adapter, qdrant_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id_1 = new_uuid7()
    service = make_service(minio_adapter, qdrant_adapter)

    sample_1 = await service.persist(
        process_id=process_id_1,
        face_id=face_id,
        sample_id=sample_id,
        aligned_bytes=b"aligned-bytes",
        media_type="image/jpeg",
        vector=normalized_vector(),
        bounding_box={},
    )
    assert sample_1.lifecycle_state == "active"

    process_id_2 = new_uuid7()
    sample_2 = await service.persist(
        process_id=process_id_2,
        face_id=face_id,
        sample_id=sample_id,
        aligned_bytes=b"aligned-bytes",
        media_type="image/jpeg",
        vector=normalized_vector(),
        bounding_box={},
    )
    assert sample_2.lifecycle_state == "active"
    assert sample_2.sample_id == sample_1.sample_id

    await cleanup(face_id, sample_id, process_id_2, f"faces/{face_id}/{sample_id}/aligned")
