from datetime import datetime
from typing import Any

from app.presentation.schemas.faces import ApiModel, FaceResultResponse


class ProcessEventResponse(ApiModel):
    event_type: str
    details: dict[str, Any]
    timestamp: datetime


class ProcessResponse(ApiModel):
    process_id: str
    process_type: str
    status: str
    face_count: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    faces: list[FaceResultResponse]
    events: list[ProcessEventResponse]
