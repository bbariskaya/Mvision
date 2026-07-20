from app.config import Settings
from app.infrastructure.database.repositories import FaceSampleRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.exceptions import ObjectNotFoundError
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter


class StorageReconciliationService:
    def __init__(
        self,
        settings: Settings,
        sample_repo: FaceSampleRepository,
        minio: MinIOAdapter,
        qdrant: QdrantAdapter,
    ):
        self._settings = settings
        self._sample_repo = sample_repo
        self._minio = minio
        self._qdrant = qdrant

    async def reconcile(
        self,
        embedding_model_version: str | None = None,
        preprocess_version: str | None = None,
        dry_run: bool = True,
    ) -> list[dict]:
        async with AsyncSessionLocal() as session:
            samples = await self._sample_repo.list_active_by_model(
                session,
                embedding_model_version=embedding_model_version or self._settings.model_version,
                preprocess_version=preprocess_version or self._settings.preprocess_version,
            )

        mismatches: list[dict] = []
        for sample in samples:
            issues: list[str] = []

            try:
                info = await self._minio.stat_aligned_sample(sample.object_key)
                if info.sha256 != sample.sha256:
                    issues.append("checksum_mismatch")
            except ObjectNotFoundError:
                issues.append("missing_object")
            except Exception:
                issues.append("object_store_error")

            try:
                point = await self._qdrant.get(sample.sample_id)
                if point is None:
                    issues.append("missing_vector")
                else:
                    payload = point.get("payload") or {}
                    if payload.get("active") is not True:
                        issues.append("inactive_vector")
                    if payload.get("embedding_model_version") != sample.embedding_model_version:
                        issues.append("model_version_mismatch")
                    if payload.get("preprocess_version") != sample.preprocess_version:
                        issues.append("preprocess_version_mismatch")
            except Exception:
                issues.append("vector_store_error")

            if issues:
                mismatches.append(
                    {
                        "sample_id": sample.sample_id,
                        "face_id": sample.face_id,
                        "object_key": sample.object_key,
                        "issues": issues,
                    }
                )
                if not dry_run:
                    await self._repair(sample.sample_id)

        return mismatches

    async def _repair(self, sample_id: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._sample_repo.set_inactive(session, sample_id=sample_id)
                await session.commit()
        except Exception:
            pass
        try:
            await self._qdrant.delete(sample_id)
        except Exception:
            pass
