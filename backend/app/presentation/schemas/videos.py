from datetime import datetime
from typing import Any, Literal

from app.presentation.schemas.faces import ApiModel


class VideoSubmitResponse(ApiModel):
    job_id: str
    process_id: str
    status: Literal["pending"]
    status_url: str
    result_url: str


class VideoMetadataResponse(ApiModel):
    duration: float
    fps: float
    width: int
    height: int
    total_frames: int
    processed_frames: int
    sampling: dict[str, Any]
    source_available: bool


class VideoJobResponse(ApiModel):
    job_id: str
    process_id: str
    status: Literal[
        "pending", "processing", "cancelling", "cancelled", "completed", "failed"
    ]
    stage: str
    progress_percent: float
    cancellation_requested: bool
    error_code: str | None
    video: VideoMetadataResponse
    person_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
