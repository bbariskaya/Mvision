from typing import Any

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    FaceSampleRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.vector_store.qdrant_adapter import QdrantAdapter
from app.services.exceptions import NotFoundError, ValidationError


class IdentityService:
    def __init__(
        self,
        identity_repo: FaceIdentityRepository,
        sample_repo: FaceSampleRepository,
        process_repo: ProcessRecordRepository,
        result_repo: RecognitionResultRepository,
        event_repo: ProcessEventRepository,
        qdrant: QdrantAdapter,
    ):
        self._identity_repo = identity_repo
        self._sample_repo = sample_repo
        self._process_repo = process_repo
        self._result_repo = result_repo
        self._event_repo = event_repo
        self._qdrant = qdrant

    async def get(self, face_id: str, process_id: str | None = None) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            identity = await self._identity_repo.get_active_by_id(session, face_id)
            if identity is None:
                raise NotFoundError("Face identity not found")
            samples = await self._sample_repo.list_by_face(session, face_id, True)
            return self._identity_dict(identity, len(samples), process_id)

    async def update(self, face_id: str, name: str, metadata: dict) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("name must not be empty", "INVALID_NAME")
        process_id = new_uuid7()
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "update")
            identity = await self._identity_repo.update_known(
                session, face_id, clean_name, metadata
            )
            if identity is None:
                await self._process_repo.fail(session, process_id, "NOT_FOUND")
                await session.commit()
                raise NotFoundError("Face identity not found", process_id)
            samples = await self._sample_repo.list_by_face(session, face_id, True)
            await self._process_repo.complete(
                session,
                process_id,
                1,
                details={
                    "operation": "update",
                    "face_count": 1,
                    "faces": [
                        {"face_id": identity.face_id, "status": identity.lifecycle_status}
                    ],
                },
            )
            await session.commit()
        await self._log_event(process_id, "identity_updated", {"face_id": face_id})
        return self._identity_dict(identity, len(samples), process_id)

    async def delete(self, face_id: str) -> dict[str, Any]:
        process_id = new_uuid7()
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "delete")
            identity = await self._identity_repo.soft_delete(session, face_id)
            if identity is None:
                await self._process_repo.fail(session, process_id, "NOT_FOUND")
                await session.commit()
                raise NotFoundError("Face identity not found", process_id)
            sample_ids = await self._sample_repo.deactivate_by_face(session, face_id)
            await self._process_repo.complete(
                session,
                process_id,
                1,
                details={
                    "operation": "delete",
                    "face_count": 1,
                    "faces": [
                        {"face_id": identity.face_id, "status": identity.lifecycle_status}
                    ],
                },
            )
            await session.commit()
        for sample_id in sample_ids:
            await self._qdrant.deactivate(sample_id)
        await self._log_event(
            process_id,
            "identity_deleted",
            {"face_id": face_id, "sample_count": len(sample_ids)},
        )
        return {"process_id": process_id, "face_id": face_id, "deleted": True}

    async def history(self, face_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            identity = await self._identity_repo.get_by_id(session, face_id)
            if identity is None:
                raise NotFoundError("Face identity not found")
            results = await self._result_repo.get_by_face(session, face_id)
        return {
            "face_id": face_id,
            "history": [
                {
                    "process_id": result.process_id,
                    "timestamp": result.created_at,
                    "status": result.status_snapshot,
                }
                for result in results
            ],
        }

    @staticmethod
    def _identity_dict(identity: Any, sample_count: int, process_id: str | None) -> dict:
        return {
            "process_id": process_id,
            "face_id": identity.face_id,
            "status": identity.lifecycle_status,
            "name": identity.name if identity.lifecycle_status == "known" else None,
            "metadata": identity.metadata_ if identity.lifecycle_status == "known" else None,
            "is_active": identity.is_active,
            "sample_count": sample_count,
            "created_at": identity.created_at,
            "updated_at": identity.updated_at,
        }

    async def _log_event(self, process_id: str, event_type: str, details: dict) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._event_repo.create(session, process_id, event_type, details)
                await session.commit()
        except Exception:
            pass
