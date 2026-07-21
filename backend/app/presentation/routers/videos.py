from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status

from app.infrastructure.database.ids import new_uuid7
from app.presentation.dependencies import get_video_job_service, get_video_upload_service
from app.presentation.schemas.videos import (
    VideoJobResponse,
    VideoResultResponse,
    VideoSubmitResponse,
)
from app.services.exceptions import ValidationError
from app.services.video_job_service import VideoJobService
from app.services.video_upload_service import VideoUploadService

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


def _job_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValidationError("jobId must be a valid UUID", "INVALID_ID") from exc


@router.post(
    "/recognize", response_model=VideoSubmitResponse, status_code=status.HTTP_202_ACCEPTED
)
async def recognize_video(
    video: Annotated[UploadFile, File()],
    service: Annotated[VideoUploadService, Depends(get_video_upload_service)],
    sampling_mode: Annotated[str | None, Form(alias="samplingMode")] = None,
    every_n_frames: Annotated[int | None, Form(alias="everyNFrames")] = None,
    frames_per_second: Annotated[float | None, Form(alias="framesPerSecond")] = None,
) -> dict:
    return await service.submit(
        video,
        sampling_mode,
        every_n_frames,
        frames_per_second,
        new_uuid7(),
    )


@router.get("/jobs/{job_id}", response_model=VideoJobResponse)
async def get_video_job(
    job_id: str,
    service: Annotated[VideoJobService, Depends(get_video_job_service)],
) -> dict:
    return await service.get(_job_id(job_id))


@router.delete("/jobs/{job_id}", response_model=VideoJobResponse)
async def cancel_video_job(
    job_id: str,
    service: Annotated[VideoJobService, Depends(get_video_job_service)],
) -> dict:
    return await service.cancel(_job_id(job_id))


@router.get("/jobs/{job_id}/result", response_model=VideoResultResponse)
async def get_video_result(
    job_id: str,
    service: Annotated[VideoJobService, Depends(get_video_job_service)],
) -> dict:
    return await service.result(_job_id(job_id))


@router.get("/jobs/{job_id}/video")
async def get_video_source(
    job_id: str,
    service: Annotated[VideoJobService, Depends(get_video_job_service)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    source = await service.source(_job_id(job_id), range_header)
    return Response(
        content=source["data"],
        media_type=source["content_type"],
        status_code=source["status_code"],
        headers=source["headers"],
    )
