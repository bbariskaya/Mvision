from typing import Any

from app.infrastructure.database.repositories import (
    ProcessEventRepository,
    ProcessRecordRepository,
    RecognitionResultRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.services.exceptions import NotFoundError


class ProcessQueryService:
    def __init__(
        self,
        process_repo: ProcessRecordRepository,
        result_repo: RecognitionResultRepository,
        event_repo: ProcessEventRepository,
    ):
        self._process_repo = process_repo
        self._result_repo = result_repo
        self._event_repo = event_repo

    async def get(self, process_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            process = await self._process_repo.get_by_id(session, process_id)
            if process is None:
                raise NotFoundError("Process not found")
            results = await self._result_repo.get_by_process(session, process_id)
            events = await self._event_repo.get_by_process(session, process_id)
        return {
            "process_id": process.process_id,
            "process_type": process.process_type,
            "status": process.status,
            "face_count": process.face_count,
            "error_code": process.error_code,
            "created_at": process.created_at,
            "completed_at": process.completed_at,
            "faces": [
                {
                    "face_id": result.face_id,
                    "status": result.status_snapshot,
                    "name": result.name_snapshot,
                    "metadata": (
                        result.metadata_snapshot if result.status_snapshot == "known" else None
                    ),
                    "bounding_box": result.bounding_box,
                    "confidence": result.match_confidence,
                }
                for result in results
            ],
            "events": [
                {
                    "event_type": event.event_type,
                    "details": event.sanitized_details,
                    "timestamp": event.created_at,
                }
                for event in events
            ],
        }
