from app.config import Settings
from app.infrastructure.database.models import FaceIdentity, FaceSample
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.exceptions import ObjectStorageError
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.vector_store.exceptions import VectorStoreError, VectorValidationError
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services.exceptions import ServiceError, StorageError
from app.services.exceptions import VectorStoreError as VecErr


class FaceSamplePersistenceService:
    def __init__(
        self,
        settings: Settings,
        identity_repo: FaceIdentityRepository,
        sample_repo: FaceSampleRepository,
        process_repo: ProcessRecordRepository,
        event_repo: ProcessEventRepository,
        minio: MinIOAdapter,
        qdrant: QdrantAdapter,
    ):
        self._settings = settings
        self._identity_repo = identity_repo
        self._sample_repo = sample_repo
        self._process_repo = process_repo
        self._event_repo = event_repo
        self._minio = minio
        self._qdrant = qdrant

    async def persist(
        self,
        process_id: str,
        face_id: str,
        sample_id: str,
        aligned_bytes: bytes,
        media_type: str,
        vector: list[float],
        bounding_box: dict,
        landmarks: dict | None = None,
        quality: dict | None = None,
        detector_version: str = "",
        embedding_model_version: str = "",
        alignment_version: str = "",
        preprocess_version: str = "",
        identity_status: str = "anonymous",
        name: str | None = None,
        metadata: dict | None = None,
        manage_process: bool = True,
    ) -> FaceSample:
        object_key = f"faces/{face_id}/{sample_id}/aligned"
        identity, sample, is_new = await self._ensure_identity_and_sample(
            face_id=face_id,
            sample_id=sample_id,
            identity_status=identity_status,
            name=name,
            metadata=metadata,
        )
        if not is_new and sample.lifecycle_state == "active":
            return sample

        if manage_process:
            async with AsyncSessionLocal() as session:
                await self._process_repo.create(
                    session,
                    process_id=process_id,
                    process_type="enroll",
                )
                await session.commit()

        try:
            sha256 = await self._minio.upload_aligned_sample(
                object_key=object_key,
                data=aligned_bytes,
                media_type=media_type,
                sample_id=sample_id,
            )
            await self._minio.stat_aligned_sample(object_key)
        except ObjectStorageError as exc:
            await self._record_failure(process_id, sample_id, exc.code)
            raise StorageError(f"MinIO failed: {exc}")
        except Exception as exc:
            await self._record_failure(process_id, sample_id, "STORAGE_ERROR")
            raise StorageError(f"MinIO failed: {exc}")

        async with AsyncSessionLocal() as session:
            await self._sample_repo.update_blob_ready(
                session,
                sample_id=sample_id,
                bucket=self._settings.minio_bucket_faces,
                object_key=object_key,
                media_type=media_type,
                sha256=sha256,
                detector_version=detector_version,
                embedding_model_version=embedding_model_version,
                alignment_version=alignment_version,
                preprocess_version=preprocess_version,
                bounding_box=bounding_box,
                landmarks=landmarks,
                quality=quality,
            )
            await session.commit()
        await self._log_event(
            process_id,
            "sample_blob_ready",
            {"sample_id": sample_id, "object_key": object_key},
        )

        try:
            await self._qdrant.upsert(
                sample_id=sample_id,
                face_id=face_id,
                vector=vector,
                active=True,
                embedding_model_version=embedding_model_version,
                preprocess_version=preprocess_version,
            )
        except (VectorStoreError, VectorValidationError) as exc:
            await self._record_failure(process_id, sample_id, exc.code)
            raise VecErr(f"Qdrant failed: {exc}")
        except Exception as exc:
            await self._record_failure(process_id, sample_id, "VECTOR_STORE_ERROR")
            raise VecErr(f"Qdrant failed: {exc}")

        async with AsyncSessionLocal() as session:
            active_sample = await self._sample_repo.set_active(session, sample_id=sample_id)
            if active_sample is None:
                await self._record_failure(process_id, sample_id, "PG_FINALIZATION_ERROR")
                raise ServiceError(
                    "PG finalization failed",
                    "Internal error finalizing sample.",
                    "PG_FINALIZATION_ERROR",
                )
            if manage_process:
                await self._process_repo.complete(session, process_id=process_id, face_count=1)
            await session.commit()
        await self._log_event(
            process_id,
            "sample_active",
            {"sample_id": sample_id, "object_key": object_key},
        )

        return active_sample

    async def _ensure_identity_and_sample(
        self,
        face_id: str,
        sample_id: str,
        identity_status: str,
        name: str | None,
        metadata: dict | None,
    ) -> tuple[FaceIdentity, FaceSample, bool]:
        async with AsyncSessionLocal() as session:
            identity = await self._identity_repo.get_by_id(session, face_id=face_id)
            if identity is None:
                identity = await self._identity_repo.create(
                    session,
                    face_id=face_id,
                    lifecycle_status=identity_status,
                    name=name,
                    metadata=metadata or {},
                )

            sample = await self._sample_repo.get_by_id(session, sample_id=sample_id)
            is_new = sample is None
            if sample is None:
                sample = await self._sample_repo.create_pending(
                    session,
                    sample_id=sample_id,
                    face_id=face_id,
                )

            await session.commit()
            return identity, sample, is_new

    async def _record_failure(
        self,
        process_id: str,
        sample_id: str,
        error_code: str,
    ) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._sample_repo.set_failed(
                    session,
                    sample_id=sample_id,
                    failure_code=error_code,
                )
                await self._process_repo.fail(
                    session,
                    process_id=process_id,
                    error_code=error_code,
                )
                await session.commit()
            await self._log_event(
                process_id,
                "sample_persistence_failed",
                {"sample_id": sample_id, "error_code": error_code},
            )
        except Exception:
            pass

    async def _log_event(self, process_id: str, event_type: str, details: dict) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._event_repo.create(
                    session,
                    process_id=process_id,
                    event_type=event_type,
                    sanitized_details=details,
                )
                await session.commit()
        except Exception:
            pass
