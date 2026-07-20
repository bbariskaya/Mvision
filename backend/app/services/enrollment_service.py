import json
from typing import Any

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    FaceIdentityRepository,
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.gpu.worker_pool import GpuWorkerError, GpuWorkerPool
from app.services.exceptions import InferenceError, NotFoundError, ValidationError
from app.services.face_matcher import FaceMatcher
from app.services.face_sample_persistence_service import FaceSamplePersistenceService


class EnrollmentService:
    def __init__(
        self,
        settings: Settings,
        worker_pool: GpuWorkerPool,
        matcher: FaceMatcher,
        sample_persistence: FaceSamplePersistenceService,
        identity_repo: FaceIdentityRepository,
        process_repo: ProcessRecordRepository,
        result_repo: RecognitionResultRepository,
        event_repo: ProcessEventRepository,
    ):
        self._settings = settings
        self._workers = worker_pool
        self._matcher = matcher
        self._samples = sample_persistence
        self._identity_repo = identity_repo
        self._process_repo = process_repo
        self._result_repo = result_repo
        self._event_repo = event_repo

    @staticmethod
    def parse_metadata(raw: str | None) -> dict[str, Any]:
        if raw is None or not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError("metadata must be a JSON object", "INVALID_METADATA") from exc
        if not isinstance(value, dict):
            raise ValidationError("metadata must be a JSON object", "INVALID_METADATA")
        return value

    async def enroll(
        self,
        image: bytes,
        name: str,
        metadata: dict[str, Any],
        face_id: str | None = None,
        process_id: str | None = None,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("name must not be empty", "INVALID_NAME")
        process_id = process_id or new_uuid7()
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "enroll")
            await session.commit()
        try:
            result = await self._workers.process(image, process_id)
            if len(result.faces) != 1:
                code = "NO_FACE" if not result.faces else "MULTIPLE_FACES"
                raise ValidationError(
                    "Enrollment image must contain exactly one face", code, process_id
                )
            detection = result.faces[0]
            embedding = list(detection.embedding)
            if face_id is not None:
                async with AsyncSessionLocal() as session:
                    identity = await self._identity_repo.get_active_by_id(session, face_id)
                if identity is None:
                    raise NotFoundError("Face identity not found", process_id)
                selected_face_id = identity.face_id
            else:
                match = await self._matcher.match(embedding)
                selected_face_id = match.identity.face_id if match else new_uuid7()

            async with AsyncSessionLocal() as session:
                existing = await self._identity_repo.get_active_by_id(session, selected_face_id)
                if existing is not None:
                    await self._identity_repo.update_known(
                        session, selected_face_id, clean_name, metadata
                    )
                    await session.commit()

            sample_id = new_uuid7()
            box = {
                "x": detection.x,
                "y": detection.y,
                "width": detection.width,
                "height": detection.height,
            }
            await self._samples.persist(
                process_id=process_id,
                face_id=selected_face_id,
                sample_id=sample_id,
                aligned_bytes=detection.aligned_jpeg or image,
                media_type="image/jpeg",
                vector=embedding,
                bounding_box=box,
                landmarks={
                    "points": [
                        [detection.landmarks_xy[index], detection.landmarks_xy[index + 1]]
                        for index in range(0, 10, 2)
                    ]
                },
                detector_version=self._settings.detector_version,
                embedding_model_version=self._settings.model_version,
                alignment_version=self._settings.alignment_version,
                preprocess_version=self._settings.preprocess_version,
                identity_status="known",
                name=clean_name,
                metadata=metadata,
                manage_process=False,
            )
            face = {
                "face_id": selected_face_id,
                "status": "known",
                "name": clean_name,
                "metadata": metadata,
                "bounding_box": box,
                "confidence": 1.0,
            }
            async with AsyncSessionLocal() as session:
                await self._result_repo.create(
                    session,
                    result_id=new_uuid7(),
                    process_id=process_id,
                    detection_ordinal=0,
                    face_id=selected_face_id,
                    status_snapshot="known",
                    name_snapshot=clean_name,
                    metadata_snapshot=metadata,
                    bounding_box=box,
                    detector_confidence=detection.detector_confidence,
                    match_confidence=1.0,
                    matched_sample_id=sample_id,
                )
                await self._process_repo.complete(session, process_id, 1)
                await session.commit()
            await self._log_event(
                process_id,
                "enrollment_completed",
                {"face_id": selected_face_id, "status": "known"},
            )
            return {"process_id": process_id, "face_count": 1, "faces": [face]}
        except ValidationError:
            await self._fail(process_id, "INVALID_ENROLLMENT")
            raise
        except NotFoundError:
            await self._fail(process_id, "NOT_FOUND")
            raise
        except GpuWorkerError as exc:
            await self._fail(process_id, "INFERENCE_ERROR")
            raise InferenceError(str(exc), process_id) from exc
        except Exception as exc:
            await self._fail(process_id, "ENROLLMENT_ERROR")
            if hasattr(exc, "process_id"):
                exc.process_id = process_id
                raise
            raise InferenceError(str(exc), process_id) from exc

    async def reject(self, process_id: str, code: str) -> None:
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "enroll")
            await self._process_repo.fail(session, process_id, code)
            await session.commit()
        await self._log_event(process_id, "enrollment_rejected", {"error_code": code})

    async def _fail(self, process_id: str, code: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._process_repo.fail(session, process_id, code)
                await session.commit()
            await self._log_event(process_id, "enrollment_failed", {"error_code": code})
        except Exception:
            pass

    async def _log_event(self, process_id: str, event_type: str, details: dict) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._event_repo.create(session, process_id, event_type, details)
                await session.commit()
        except Exception:
            pass
