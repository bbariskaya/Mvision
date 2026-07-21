from dataclasses import dataclass

from app.config import Settings
from app.infrastructure.database.models import FaceIdentity
from app.infrastructure.database.repositories import FaceIdentityRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter


@dataclass(frozen=True)
class FaceMatch:
    identity: FaceIdentity
    sample_id: str
    score: float


class FaceMatcher:
    def __init__(
        self,
        settings: Settings,
        identity_repo: FaceIdentityRepository,
        qdrant: QdrantAdapter,
    ):
        self._settings = settings
        self._identity_repo = identity_repo
        self._qdrant = qdrant

    async def match(self, embedding: list[float]) -> FaceMatch | None:
        candidates = await self.candidates(embedding, minimum_score=0.0)
        for candidate in candidates:
            threshold = (
                self._settings.recognition_threshold
                if candidate.identity.lifecycle_status == "known"
                else self._settings.anonymous_threshold
            )
            if candidate.score >= threshold:
                return candidate
        return None

    async def candidates(
        self, embedding: list[float], *, minimum_score: float
    ) -> list[FaceMatch]:
        candidates = await self._qdrant.search(
            embedding,
            top_k=10,
            embedding_model_version=self._settings.model_version,
            preprocess_version=self._settings.preprocess_version,
        )
        matches: list[FaceMatch] = []
        async with AsyncSessionLocal() as session:
            for candidate in candidates:
                payload = candidate.get("payload") or {}
                face_id = payload.get("face_id")
                if not face_id:
                    continue
                identity = await self._identity_repo.get_active_by_id(session, str(face_id))
                if identity is None:
                    continue
                score = min(1.0, max(0.0, float(candidate["score"])))
                if score >= minimum_score:
                    matches.append(
                        FaceMatch(identity, str(candidate["sample_id"]), score)
                    )
        return matches
