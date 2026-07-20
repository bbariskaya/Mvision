import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.object_storage.exceptions import (
    ObjectNotFoundError,
    ObjectValidationError,
)


@pytest.mark.asyncio
async def test_ensure_bucket_idempotent(minio_adapter):
    await minio_adapter.ensure_bucket()
    await minio_adapter.ensure_bucket()


@pytest.mark.asyncio
async def test_upload_stat_get_delete_roundtrip(minio_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    object_key = f"faces/{face_id}/{sample_id}/aligned"
    data = b"fake-aligned-face-bytes"

    sha256 = await minio_adapter.upload_aligned_sample(
        object_key=object_key,
        data=data,
        media_type="image/jpeg",
        sample_id=sample_id,
    )

    info = await minio_adapter.stat_aligned_sample(object_key)
    assert info.object_key == object_key
    assert info.size == len(data)
    assert info.sha256 == sha256
    assert info.metadata.get("x-amz-meta-sample-id") == sample_id

    fetched, fetched_info = await minio_adapter.get_aligned_sample(object_key)
    assert fetched == data
    assert fetched_info.sha256 == sha256

    await minio_adapter.delete_aligned_sample(object_key)

    with pytest.raises(ObjectNotFoundError):
        await minio_adapter.stat_aligned_sample(object_key)


@pytest.mark.asyncio
async def test_invalid_object_key_rejected(minio_adapter):
    with pytest.raises(ObjectValidationError):
        await minio_adapter.upload_aligned_sample(
            object_key="invaalid",
            data=b"x",
            media_type="image/jpeg",
            sample_id=new_uuid7(),
        )


@pytest.mark.asyncio
async def test_unsupported_media_type_rejected(minio_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    with pytest.raises(ObjectValidationError):
        await minio_adapter.upload_aligned_sample(
            object_key=f"faces/{face_id}/{sample_id}/aligned",
            data=b"x",
            media_type="application/octet-stream",
            sample_id=sample_id,
        )


@pytest.mark.asyncio
async def test_size_limit_rejected(minio_adapter):
    face_id = new_uuid7()
    sample_id = new_uuid7()
    minio_adapter._max_bytes = 10
    with pytest.raises(ObjectValidationError):
        await minio_adapter.upload_aligned_sample(
            object_key=f"faces/{face_id}/{sample_id}/aligned",
            data=b"x" * 11,
            media_type="image/jpeg",
            sample_id=sample_id,
        )
