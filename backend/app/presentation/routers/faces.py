from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.infrastructure.database.ids import new_uuid7
from app.presentation.dependencies import (
    get_container,
    get_enrollment_service,
    get_identity_service,
    get_recognition_service,
    get_video_job_service,
)
from app.presentation.schemas.faces import (
    DeleteFaceResponse,
    FaceHistoryResponse,
    FaceIdentityResponse,
    FaceUpdateRequest,
    RecognitionResponse,
)
from app.presentation.schemas.videos import FaceAppearancesResponse
from app.services.enrollment_service import EnrollmentService
from app.services.exceptions import ValidationError
from app.services.identity_service import IdentityService
from app.services.image_validation import normalize_image
from app.services.recognition_service import RecognitionService
from app.services.video_job_service import VideoJobService

router = APIRouter(prefix="/api/v1/faces", tags=["faces"])


async def _read_image(image: UploadFile) -> bytes:
    settings = get_container().settings
    content_type = image.content_type or ""
    if content_type not in {"image/jpeg", "image/jpg", "image/png"}:
        raise ValidationError("Only JPEG and PNG images are supported", "UNSUPPORTED_MEDIA_TYPE")
    data = await image.read(settings.max_upload_bytes + 1)
    return normalize_image(data, content_type, settings.max_upload_bytes)


def _validate_uuid(value: str, field: str = "faceId") -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValidationError(f"{field} must be a valid UUID", "INVALID_ID") from exc


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize_face(
    image: Annotated[UploadFile, File()],
    service: Annotated[RecognitionService, Depends(get_recognition_service)],
) -> dict:
    process_id = new_uuid7()
    try:
        data = await _read_image(image)
    except ValidationError as exc:
        await service.reject(process_id, exc.error_code)
        exc.process_id = process_id
        raise
    return await service.recognize(data, process_id)


@router.post("/enroll", response_model=RecognitionResponse, status_code=status.HTTP_201_CREATED)
async def enroll_face(
    image: Annotated[UploadFile, File()],
    name: Annotated[str, Form(min_length=1, max_length=255)],
    service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    metadata: Annotated[str | None, Form()] = None,
    face_id: Annotated[str | None, Form(alias="faceId")] = None,
) -> dict:
    process_id = new_uuid7()
    try:
        selected_id = _validate_uuid(face_id) if face_id else None
        parsed_metadata = service.parse_metadata(metadata)
        data = await _read_image(image)
    except ValidationError as exc:
        await service.reject(process_id, exc.error_code)
        exc.process_id = process_id
        raise
    return await service.enroll(data, name, parsed_metadata, selected_id, process_id)


@router.get("/{face_id}", response_model=FaceIdentityResponse, response_model_exclude_none=True)
async def get_face(
    face_id: str,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> dict:
    return await service.get(_validate_uuid(face_id))


@router.patch("/{face_id}", response_model=FaceIdentityResponse)
async def update_face(
    face_id: str,
    request: FaceUpdateRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> dict:
    return await service.update(_validate_uuid(face_id), request.name, request.metadata)


@router.delete("/{face_id}", response_model=DeleteFaceResponse)
async def delete_face(
    face_id: str,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> dict:
    return await service.delete(_validate_uuid(face_id))


@router.get("/{face_id}/history", response_model=FaceHistoryResponse)
async def get_face_history(
    face_id: str,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> dict:
    return await service.history(_validate_uuid(face_id))


@router.get("/{face_id}/appearances", response_model=FaceAppearancesResponse)
async def get_face_appearances(
    face_id: str,
    service: Annotated[VideoJobService, Depends(get_video_job_service)],
) -> dict:
    return await service.appearances(_validate_uuid(face_id))
