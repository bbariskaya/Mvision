import logging
from typing import Any

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories import (
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.gpu.worker_pool import GpuWorkerError, GpuWorkerPool
from app.services.exceptions import InferenceError, ServiceError
from app.services.face_matcher import FaceMatcher
from app.services.face_sample_persistence_service import FaceSamplePersistenceService
from app.services.image_validation import require_aligned_face_evidence

logger = logging.getLogger(__name__)


class RecognitionService:
    def __init__(
        self,
        settings: Settings,
        worker_pool: GpuWorkerPool,
        matcher: FaceMatcher,
        sample_persistence: FaceSamplePersistenceService,
        process_repo: ProcessRecordRepository,
        result_repo: RecognitionResultRepository,
        event_repo: ProcessEventRepository,
    ):
        self._settings = settings
        self._workers = worker_pool
        self._matcher = matcher
        self._samples = sample_persistence
        self._process_repo = process_repo
        self._result_repo = result_repo
        self._event_repo = event_repo

    async def recognize(self, image: bytes, process_id: str | None = None) -> dict[str, Any]:
        process_id = process_id or new_uuid7()
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "recognize")
            await session.commit()
        try:
            gpu_result = await self._workers.process(image, process_id)
            faces: list[dict[str, Any]] = []
            snapshots: list[dict[str, Any]] = []
            for detection in gpu_result.faces:
                embedding = list(detection.embedding)
                match = await self._matcher.match(embedding)
                if match is None:
                    face_id = new_uuid7()
                    sample_id = new_uuid7()
                    await self._samples.persist(
                        process_id=process_id,
                        face_id=face_id,
                        sample_id=sample_id,
                        aligned_bytes=require_aligned_face_evidence(detection.aligned_jpeg),
                        media_type="image/jpeg",
                        vector=embedding,
                        bounding_box=self._box(detection),
                        landmarks=self._landmarks(detection.landmarks_xy),
                        detector_version=self._settings.detector_version,
                        embedding_model_version=self._settings.model_version,
                        alignment_version=self._settings.alignment_version,
                        preprocess_version=self._settings.preprocess_version,
                        manage_process=False,
                    )
                    status = "new_anonymous"
                    name = None
                    metadata: dict | None = None
                    confidence = 0.0
                    matched_sample_id = sample_id
                else:
                    face_id = match.identity.face_id
                    status = match.identity.lifecycle_status
                    name = match.identity.name if status == "known" else None
                    metadata = match.identity.metadata_ if status == "known" else None
                    confidence = match.score
                    matched_sample_id = match.sample_id
                face = {
                    "face_id": face_id,
                    "status": status,
                    "name": name,
                    "metadata": metadata,
                    "bounding_box": self._box(detection),
                    "confidence": confidence,
                }
                faces.append(face)
                snapshots.append(
                    {
                        **face,
                        "detector_confidence": detection.detector_confidence,
                        "matched_sample_id": matched_sample_id,
                    }
                )
            async with AsyncSessionLocal() as session:
                for ordinal, snapshot in enumerate(snapshots):
                    await self._result_repo.create(
                        session,
                        result_id=new_uuid7(),
                        process_id=process_id,
                        detection_ordinal=ordinal,
                        face_id=snapshot["face_id"],
                        status_snapshot=snapshot["status"],
                        name_snapshot=snapshot["name"],
                        metadata_snapshot=snapshot["metadata"] or {},
                        bounding_box=snapshot["bounding_box"],
                        detector_confidence=snapshot["detector_confidence"],
                        match_confidence=snapshot["confidence"],
                        matched_sample_id=snapshot["matched_sample_id"],
                    )
                await self._process_repo.complete(
                    session,
                    process_id,
                    len(faces),
                    details={
                        "operation": "recognize",
                        "face_count": len(faces),
                        "faces": [
                            {"face_id": face["face_id"], "status": face["status"]}
                            for face in faces
                        ],
                    },
                )
                await session.commit()
            await self._log_event(
                process_id,
                "recognition_completed",
                {
                    "face_count": len(faces),
                    "faces": [
                        {"face_id": face["face_id"], "status": face["status"]}
                        for face in faces
                    ],
                },
            )
            return {"process_id": process_id, "face_count": len(faces), "faces": faces}
        except GpuWorkerError as exc:
            await self._fail(process_id, "INFERENCE_ERROR")
            raise InferenceError(str(exc), process_id) from exc
        except ServiceError as exc:
            exc.process_id = process_id
            await self._fail(process_id, exc.error_code)
            raise
        except Exception as exc:
            logger.exception("Recognition process %s failed", process_id)
            await self._fail(process_id, "INTERNAL_ERROR")
            raise InferenceError(str(exc), process_id) from exc

    async def reject(self, process_id: str, code: str) -> None:
        async with AsyncSessionLocal() as session:
            await self._process_repo.create(session, process_id, "recognize")
            await self._process_repo.fail(session, process_id, code)
            await session.commit()
        await self._log_event(process_id, "recognition_rejected", {"error_code": code})

    async def _fail(self, process_id: str, code: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._process_repo.fail(session, process_id, code)
                await session.commit()
            await self._log_event(process_id, "recognition_failed", {"error_code": code})
        except Exception:
            pass

    async def _log_event(self, process_id: str, event_type: str, details: dict) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._event_repo.create(session, process_id, event_type, details)
                await session.commit()
        except Exception:
            pass

    @staticmethod
    def _box(detection: Any) -> dict[str, float]:
        return {
            "x": detection.x,
            "y": detection.y,
            "width": detection.width,
            "height": detection.height,
        }

    @staticmethod
    def _landmarks(values: tuple[float, ...]) -> dict[str, list[list[float]]]:
        return {"points": [[values[index], values[index + 1]] for index in range(0, 10, 2)]}
