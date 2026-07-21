from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.presentation.schemas.faces import ApiModel


class CameraCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    rtsp_uri: SecretStr = Field(alias="rtspUri")


class CameraResponse(ApiModel):
    camera_id: UUID
    name: str
    desired_state: Literal["stopped", "running"]
    runtime_state: Literal[
        "STOPPED", "STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "FAILED"
    ]
    output_url: str | None
    created_at: datetime
    updated_at: datetime


class CameraListResponse(ApiModel):
    cameras: list[CameraResponse]


class DeleteCameraResponse(ApiModel):
    camera_id: UUID
    deleted: bool


class CameraEventResponse(ApiModel):
    event_id: UUID
    native_track_id: int
    event_type: Literal["known", "unknown"]
    face_id: UUID | None
    name: str | None
    match_score: float | None
    nearest_known_score: float | None
    detector_confidence: float
    first_seen_at: datetime
    last_seen_at: datetime
    occurred_at: datetime
    bounding_box: dict[str, Any]
    landmarks: list[float]
    quality: dict[str, Any]
    snapshot_status: Literal["pending", "ready", "failed", "unavailable"]


class CameraEventListResponse(ApiModel):
    camera_id: UUID
    events: list[CameraEventResponse]
    next_cursor: str | None


class CameraHealthResponse(ApiModel):
    camera_id: UUID
    run_id: UUID | None
    generation: int | None
    desired_state: Literal["stopped", "running"]
    runtime_state: Literal[
        "STOPPED", "STARTING", "ACTIVE", "RECONNECTING", "STOPPING", "FAILED"
    ]
    first_frame_at: datetime | None
    last_frame_at: datetime | None
    reconnect_count: int
    metrics: dict[str, Any]
    output_url: str | None
    error_code: str | None
