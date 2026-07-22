import asyncio
import math

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    QueryRequest,
    VectorParams,
)

from app.config import Settings
from app.infrastructure.vector_store.exceptions import VectorStoreError, VectorValidationError

ALLOWED_PAYLOAD_KEYS = {
    "sample_id",
    "face_id",
    "active",
    "embedding_model_version",
    "preprocess_version",
}
EXPECTED_DIMENSION = 512
L2_TOLERANCE = 1e-5


class QdrantAdapter:
    def __init__(self, settings: Settings):
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        self._client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key)
        self._collection = settings.qdrant_collection
        self._vector_size = settings.qdrant_vector_size
        distance_label = settings.qdrant_distance.upper()
        self._distance = Distance[distance_label]
        self._setup_lock = asyncio.Lock()
        self._setup_complete = False

    def _validate_payload(self, payload: dict) -> None:
        extra = set(payload.keys()) - ALLOWED_PAYLOAD_KEYS
        if extra:
            raise VectorValidationError(f"Forbidden payload keys: {sorted(extra)}")
        if payload.get("sample_id") is None or payload.get("face_id") is None:
            raise VectorValidationError("Payload must contain sample_id and face_id")

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != EXPECTED_DIMENSION:
            raise VectorValidationError(f"Vector dimension must be {EXPECTED_DIMENSION}")
        if not all(math.isfinite(v) for v in vector):
            raise VectorValidationError("Vector contains non-finite values")
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            raise VectorValidationError("Vector must be non-zero")
        if abs(norm - 1.0) > L2_TOLERANCE:
            raise VectorValidationError("Vector must be L2-normalized")

    async def setup(self) -> None:
        if self._setup_complete:
            return
        async with self._setup_lock:
            if self._setup_complete:
                return
            exists = await self._client.collection_exists(self._collection)
            if not exists:
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(
                        size=self._vector_size,
                        distance=self._distance,
                    ),
                    hnsw_config=HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                        payload_m=16,
                    ),
                )
                await self._ensure_payload_indexes()
                self._setup_complete = True
                return

            info = await self._client.get_collection(self._collection)
            actual = info.config.params.vectors
            if actual is None:
                raise VectorStoreError("Collection has no vector configuration")
            if isinstance(actual, dict):
                raise VectorStoreError("Named vectors are not supported")
            if actual.size != self._vector_size:
                raise VectorStoreError(
                    f"Collection vector size mismatch: {actual.size} != {self._vector_size}"
                )
            if actual.distance != self._distance:
                raise VectorStoreError(
                    f"Collection distance mismatch: {actual.distance} != {self._distance}"
                )
            await self._ensure_payload_indexes()
            self._setup_complete = True

    async def _ensure_payload_indexes(self) -> None:
        for field in ("active", "embedding_model_version", "preprocess_version"):
            try:
                await self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

    async def upsert(
        self,
        sample_id: str,
        face_id: str,
        vector: list[float],
        active: bool = True,
        embedding_model_version: str = "",
        preprocess_version: str = "",
    ) -> None:
        self._validate_vector(vector)
        payload = {
            "sample_id": sample_id,
            "face_id": face_id,
            "active": active,
            "embedding_model_version": embedding_model_version,
            "preprocess_version": preprocess_version,
        }
        self._validate_payload(payload)
        await self.setup()
        point = PointStruct(id=sample_id, vector=vector, payload=payload)
        await self._client.upsert(collection_name=self._collection, points=[point], wait=True)

    async def activate(self, sample_id: str) -> None:
        await self._set_active(sample_id, True)

    async def deactivate(self, sample_id: str) -> None:
        await self._set_active(sample_id, False)

    async def _set_active(self, sample_id: str, active: bool) -> None:
        await self.setup()
        await self._client.set_payload(
            collection_name=self._collection,
            payload={"active": active},
            points=[sample_id],
            wait=True,
        )

    async def delete(self, sample_id: str) -> None:
        await self.setup()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[sample_id]),
            wait=True,
        )

    async def get(self, sample_id: str) -> dict | None:
        await self.setup()
        results = await self._client.retrieve(
            collection_name=self._collection,
            ids=[sample_id],
            with_payload=True,
            with_vectors=True,
        )
        if not results:
            return None
        point = results[0]
        return {
            "sample_id": point.id,
            "vector": point.vector,
            "payload": point.payload,
        }

    async def exists(self, sample_id: str) -> bool:
        await self.setup()
        results = await self._client.retrieve(
            collection_name=self._collection,
            ids=[sample_id],
            with_payload=False,
            with_vectors=False,
        )
        return len(results) > 0

    async def search(
        self,
        vector: list[float],
        top_k: int = 5,
        filter_active: bool = True,
        embedding_model_version: str | None = None,
        preprocess_version: str | None = None,
    ) -> list[dict]:
        self._validate_vector(vector)
        await self.setup()
        conditions: list = []
        if filter_active:
            conditions.append(FieldCondition(key="active", match=MatchValue(value=True)))
        if embedding_model_version is not None:
            conditions.append(
                FieldCondition(
                    key="embedding_model_version",
                    match=MatchValue(value=embedding_model_version),
                )
            )
        if preprocess_version is not None:
            conditions.append(
                FieldCondition(
                    key="preprocess_version",
                    match=MatchValue(value=preprocess_version),
                )
            )
        search_filter = Filter(must=conditions) if conditions else None
        response = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        return [
            {
                "sample_id": r.id,
                "score": r.score,
                "payload": r.payload,
            }
            for r in response.points
        ]

    async def search_batch(
        self,
        vectors: list[list[float]],
        top_k: int = 5,
        filter_active: bool = True,
        embedding_model_version: str | None = None,
        preprocess_version: str | None = None,
    ) -> list[list[dict]]:
        for vector in vectors:
            self._validate_vector(vector)
        if not vectors:
            return []
        await self.setup()
        conditions: list = []
        if filter_active:
            conditions.append(FieldCondition(key="active", match=MatchValue(value=True)))
        if embedding_model_version is not None:
            conditions.append(
                FieldCondition(
                    key="embedding_model_version",
                    match=MatchValue(value=embedding_model_version),
                )
            )
        if preprocess_version is not None:
            conditions.append(
                FieldCondition(
                    key="preprocess_version",
                    match=MatchValue(value=preprocess_version),
                )
            )
        search_filter = Filter(must=conditions) if conditions else None
        responses = await self._client.query_batch_points(
            collection_name=self._collection,
            requests=[
                QueryRequest(
                    query=vector,
                    filter=search_filter,
                    limit=top_k,
                    with_payload=True,
                    with_vector=False,
                )
                for vector in vectors
            ],
        )
        return [
            [
                {
                    "sample_id": point.id,
                    "score": point.score,
                    "payload": point.payload,
                }
                for point in response.points
            ]
            for response in responses
        ]
