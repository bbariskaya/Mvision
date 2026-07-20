import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
)
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services import FaceSamplePersistenceService, StorageReconciliationService


@pytest_asyncio.fixture
async def db_session():
    settings = get_settings()
    database_url = os.getenv("TEST_DATABASE_URL", settings.database_url)
    engine = create_async_engine(database_url, future=True)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
def unique_id():
    return new_uuid7


@pytest_asyncio.fixture
async def minio_adapter():
    adapter = MinIOAdapter(get_settings())
    await adapter.ensure_bucket()
    yield adapter


@pytest_asyncio.fixture
async def qdrant_adapter():
    adapter = QdrantAdapter(get_settings())
    try:
        await adapter._client.delete_collection(adapter._collection)
    except Exception:
        pass
    await adapter.setup()
    yield adapter


@pytest_asyncio.fixture
def persistence_service(minio_adapter, qdrant_adapter):
    settings = get_settings()
    return FaceSamplePersistenceService(
        settings=settings,
        identity_repo=FaceIdentityRepository(),
        sample_repo=FaceSampleRepository(),
        process_repo=ProcessRecordRepository(),
        event_repo=ProcessEventRepository(),
        minio=minio_adapter,
        qdrant=qdrant_adapter,
    )


@pytest_asyncio.fixture
def reconciliation_service(minio_adapter, qdrant_adapter):
    settings = get_settings()
    return StorageReconciliationService(
        settings=settings,
        sample_repo=FaceSampleRepository(),
        minio=minio_adapter,
        qdrant=qdrant_adapter,
    )
