import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter


class _QdrantClient:
    def __init__(self) -> None:
        self.collection_exists_calls = 0
        self.create_collection_calls = 0
        self.create_payload_index_calls = 0
        self.query_batch_calls = 0
        self.batch_requests = []

    async def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls += 1
        await asyncio.sleep(0)
        return False

    async def create_collection(self, **kwargs) -> None:
        self.create_collection_calls += 1

    async def create_payload_index(self, **kwargs) -> None:
        self.create_payload_index_calls += 1

    async def query_batch_points(self, collection_name, requests):
        self.query_batch_calls += 1
        self.batch_requests = requests
        return [
            SimpleNamespace(
                points=[SimpleNamespace(id=index, score=0.9, payload={"face_id": "face"})]
            )
            for index, _request in enumerate(requests)
        ]


@pytest.mark.asyncio
async def test_setup_runs_once_for_concurrent_and_repeated_use() -> None:
    adapter = QdrantAdapter(Settings(_env_file=None))
    client = _QdrantClient()
    adapter._client = client

    await asyncio.gather(adapter.setup(), adapter.setup())
    await adapter.setup()

    assert client.collection_exists_calls == 1
    assert client.create_collection_calls == 1
    assert client.create_payload_index_calls == 3


@pytest.mark.asyncio
async def test_search_batch_sends_all_vectors_in_one_request() -> None:
    adapter = QdrantAdapter(Settings(_env_file=None))
    client = _QdrantClient()
    adapter._client = client
    vectors = [[1.0] + [0.0] * 511, [0.0, 1.0] + [0.0] * 510]

    results = await adapter.search_batch(
        vectors,
        top_k=3,
        embedding_model_version="arcface-r50-webface-v1",
        preprocess_version="arcface-v1",
    )

    assert client.query_batch_calls == 1
    assert len(client.batch_requests) == 2
    assert [result[0]["sample_id"] for result in results] == [0, 1]
