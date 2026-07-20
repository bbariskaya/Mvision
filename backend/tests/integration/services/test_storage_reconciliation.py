import pytest
import pytest_asyncio

from app.config import get_settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services import FaceSamplePersistenceService, StorageReconciliationService
from tests.integration.helpers import normalized_vector


def make_persistence_service(minio, qdrant):
    return FaceSamplePersistenceService(
        settings=get_settings(),
        identity_repo=FaceIdentityRepository(),
        sample_repo=FaceSampleRepository(),
        process_repo=ProcessRecordRepository(),
        event_repo=ProcessEventRepository(),
        minio=minio,
        qdrant=qdrant,
    )


@pytest_asyncio.fixture
async def persisted_sample(minio_adapter, qdrant_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    process_id = new_uuid7()
    object_key = f"faces/{face_id}/{sample_id}/aligned"
    service = make_persistence_service(minio_adapter, qdrant_adapter)
    await service.persist(
        process_id=process_id,
        face_id=face_id,
        sample_id=sample_id,
        aligned_bytes=b"aligned-bytes",
        media_type="image/jpeg",
        vector=normalized_vector(),
        bounding_box={"x": 0, "y": 0, "width": 1, "height": 1},
        embedding_model_version="arcface_r50_webface4m_v1",
        preprocess_version="five-point-umeyama-112x112",
    )
    yield {
        "face_id": face_id,
        "sample_id": sample_id,
        "process_id": process_id,
        "object_key": object_key,
        "service": service,
    }
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
async def test_reconcile_reports_no_mismatches_for_consistent_store(
    minio_adapter, qdrant_adapter, persisted_sample
):
    service = StorageReconciliationService(
        settings=get_settings(),
        sample_repo=FaceSampleRepository(),
        minio=minio_adapter,
        qdrant=qdrant_adapter,
    )
    mismatches = await service.reconcile(dry_run=True)
    sample_ids = {m["sample_id"] for m in mismatches}
    assert persisted_sample["sample_id"] not in sample_ids


@pytest.mark.asyncio
async def test_reconcile_detects_missing_object_dry_run_no_mutation(
    minio_adapter, qdrant_adapter, persisted_sample
):
    await minio_adapter.delete_aligned_sample(persisted_sample["object_key"])

    service = StorageReconciliationService(
        settings=get_settings(),
        sample_repo=FaceSampleRepository(),
        minio=minio_adapter,
        qdrant=qdrant_adapter,
    )
    mismatches = await service.reconcile(dry_run=True)
    sample_mismatch = next(
        (m for m in mismatches if m["sample_id"] == persisted_sample["sample_id"]),
        None,
    )

    assert sample_mismatch is not None
    assert "missing_object" in sample_mismatch["issues"]

    async with AsyncSessionLocal() as session:
        sample = await FaceSampleRepository().get_by_id(
            session, sample_id=persisted_sample["sample_id"]
        )
        assert sample.is_active is True


@pytest.mark.asyncio
async def test_reconcile_detects_missing_vector_dry_run_no_mutation(
    minio_adapter, qdrant_adapter, persisted_sample
):
    await qdrant_adapter.delete(persisted_sample["sample_id"])

    service = StorageReconciliationService(
        settings=get_settings(),
        sample_repo=FaceSampleRepository(),
        minio=minio_adapter,
        qdrant=qdrant_adapter,
    )
    mismatches = await service.reconcile(dry_run=True)
    sample_mismatch = next(
        (m for m in mismatches if m["sample_id"] == persisted_sample["sample_id"]),
        None,
    )

    assert sample_mismatch is not None
    assert "missing_vector" in sample_mismatch["issues"]

    async with AsyncSessionLocal() as session:
        sample = await FaceSampleRepository().get_by_id(
            session, sample_id=persisted_sample["sample_id"]
        )
        assert sample.is_active is True
