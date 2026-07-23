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


class VideoDetectionResponse(ApiModel):
    frame: int
    timestamp: float
    bounding_box: dict[str, float]
    confidence: float
    landmarks: list[dict[str, float]]


class VideoAppearanceIntervalResponse(ApiModel):
    start: float
    end: float
    start_frame: int
    end_frame: int


class VideoPersonResponse(ApiModel):
    face_id: str
    track_id: str
    status: Literal["known", "anonymous", "new_anonymous"]
    name: str | None
    metadata: dict[str, Any]
    first_seen: float
    last_seen: float
    total_duration: float
    confidence: float
    appearances: list[VideoAppearanceIntervalResponse]
    detections: list[VideoDetectionResponse]


class VideoResultResponse(ApiModel):
    job_id: str
    process_id: str
    status: Literal["completed"]
    video: VideoMetadataResponse
    person_count: int
    persons: list[VideoPersonResponse]


class FaceVideoAppearanceResponse(ApiModel):
    job_id: str
    process_id: str
    video_url: str
    track_id: str
    first_seen: float
    last_seen: float
    intervals: list[VideoAppearanceIntervalResponse]
    source_available: bool
    created_at: datetime


class FaceAppearancesResponse(ApiModel):
    face_id: str
    appearances: list[FaceVideoAppearanceResponse]
