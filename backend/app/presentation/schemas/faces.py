from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class BoundingBox(ApiModel):
    x: float
    y: float
    width: float
    height: float


class FaceResultResponse(ApiModel):
    face_id: str
    status: Literal["known", "anonymous", "new_anonymous"]
    name: str | None
    metadata: dict[str, Any] | None
    bounding_box: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)


class RecognitionResponse(ApiModel):
    process_id: str
    face_count: int
    faces: list[FaceResultResponse]


class FaceIdentityResponse(ApiModel):
    process_id: str | None = None
    face_id: str
    status: Literal["known", "anonymous"]
    name: str | None
    metadata: dict[str, Any] | None
    is_active: bool
    sample_count: int = 0
    created_at: datetime
    updated_at: datetime


class FaceUpdateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FaceHistoryItem(ApiModel):
    process_id: str
    timestamp: datetime
    status: Literal["known", "anonymous", "new_anonymous"]


class FaceHistoryResponse(ApiModel):
    face_id: str
    history: list[FaceHistoryItem]


class DeleteFaceResponse(ApiModel):
    process_id: str
    face_id: str
    deleted: bool
