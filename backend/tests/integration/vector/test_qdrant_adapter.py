import pytest

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.vector_store.exceptions import VectorValidationError
from tests.integration.helpers import normalized_vector


@pytest.mark.asyncio
async def test_setup_idempotent(qdrant_adapter):
    await qdrant_adapter.setup()
    await qdrant_adapter.setup()


@pytest.mark.asyncio
async def test_upsert_and_retrieve(qdrant_adapter):
    sample_id = new_uuid7()
    face_id = new_uuid7()
    vector = normalized_vector()

    await qdrant_adapter.upsert(
        sample_id=sample_id,
        face_id=face_id,
        vector=vector,
        embedding_model_version="arcface_r50_webface4m_v1",
        preprocess_version="five-point-umeyama-112x112",
    )

    point = await qdrant_adapter.get(sample_id)
    assert point is not None
    assert point["sample_id"] == sample_id
    assert point["payload"]["face_id"] == face_id
    assert point["payload"]["active"] is True
    assert point["payload"]["embedding_model_version"] == "arcface_r50_webface4m_v1"
    assert point["payload"]["preprocess_version"] == "five-point-umeyama-112x112"

    await qdrant_adapter.delete(sample_id)


@pytest.mark.asyncio
async def test_exists_and_activate_deactivate(qdrant_adapter):
    sample_id = new_uuid7()
    face_id = new_uuid7()
    await qdrant_adapter.upsert(
        sample_id=sample_id,
        face_id=face_id,
        vector=normalized_vector(),
    )
    assert await qdrant_adapter.exists(sample_id) is True

    await qdrant_adapter.deactivate(sample_id)
    point = await qdrant_adapter.get(sample_id)
    assert point["payload"]["active"] is False

    await qdrant_adapter.activate(sample_id)
    point = await qdrant_adapter.get(sample_id)
    assert point["payload"]["active"] is True

    await qdrant_adapter.delete(sample_id)


@pytest.mark.asyncio
async def test_search_with_active_and_version_filter(qdrant_adapter):
    sample_id = new_uuid7()
    face_id = new_uuid7()
    vector = normalized_vector()
    await qdrant_adapter.upsert(
        sample_id=sample_id,
        face_id=face_id,
        vector=vector,
        embedding_model_version="m1",
        preprocess_version="p1",
    )

    results = await qdrant_adapter.search(
        vector=vector,
        embedding_model_version="m1",
        preprocess_version="p1",
    )
    assert len(results) == 1
    assert results[0]["sample_id"] == sample_id

    results = await qdrant_adapter.search(
        vector=vector,
        filter_active=False,
        embedding_model_version="m1",
        preprocess_version="p1",
    )
    assert len(results) == 1

    results = await qdrant_adapter.search(
        vector=vector,
        embedding_model_version="other",
        preprocess_version="p1",
    )
    assert len(results) == 0

    await qdrant_adapter.delete(sample_id)


@pytest.mark.asyncio
async def test_payload_allowlist_contains_no_pii(qdrant_adapter):
    sample_id = new_uuid7()
    face_id = new_uuid7()
    await qdrant_adapter.upsert(
        sample_id=sample_id,
        face_id=face_id,
        vector=normalized_vector(),
        embedding_model_version="m1",
        preprocess_version="p1",
    )

    point = await qdrant_adapter.get(sample_id)
    assert point is not None
    payload_keys = set(point["payload"].keys())
    allowed_keys = {
        "sample_id",
        "face_id",
        "active",
        "embedding_model_version",
        "preprocess_version",
    }
    assert payload_keys == allowed_keys

    await qdrant_adapter.delete(sample_id)


@pytest.mark.asyncio
async def test_invalid_vector_dimension_rejected(qdrant_adapter):
    with pytest.raises(VectorValidationError):
        await qdrant_adapter.upsert(
            sample_id=new_uuid7(),
            face_id=new_uuid7(),
            vector=[0.0] * 100,
        )


@pytest.mark.asyncio
async def test_non_normalized_vector_rejected(qdrant_adapter):
    with pytest.raises(VectorValidationError):
        await qdrant_adapter.upsert(
            sample_id=new_uuid7(),
            face_id=new_uuid7(),
            vector=[0.5] * 512,
        )


@pytest.mark.asyncio
async def test_non_finite_vector_rejected(qdrant_adapter):
    vector = normalized_vector()
    vector[0] = float("nan")
    with pytest.raises(VectorValidationError):
        await qdrant_adapter.upsert(
            sample_id=new_uuid7(),
            face_id=new_uuid7(),
            vector=vector,
        )


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(qdrant_adapter):
    point = await qdrant_adapter.get(new_uuid7())
    assert point is None
