from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.presentation.controllers import cameras as controller
from app.presentation.dependencies import get_live_camera_service
from app.presentation.schemas.cameras import (
    CameraCreateRequest,
    CameraEventListResponse,
    CameraHealthResponse,
    CameraListResponse,
    CameraResponse,
    DeleteCameraResponse,
)
from app.services.live_camera_service import LiveCameraService

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def register_camera(
    request: CameraCreateRequest,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.register_camera(request, service)


@router.get("", response_model=CameraListResponse)
async def list_cameras(
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.list_cameras(service)


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.get_camera(camera_id, service)


@router.post("/{camera_id}/start", response_model=CameraResponse)
async def start_camera(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.start_camera(camera_id, service)


@router.post("/{camera_id}/stop", response_model=CameraResponse)
async def stop_camera(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.stop_camera(camera_id, service)


@router.delete("/{camera_id}", response_model=DeleteCameraResponse)
async def delete_camera(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.delete_camera(camera_id, service)


@router.get("/{camera_id}/events", response_model=CameraEventListResponse)
async def list_camera_events(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    return await controller.list_camera_events(camera_id, limit, service)


@router.get("/{camera_id}/events/{event_id}/snapshot")
async def get_camera_event_snapshot(
    camera_id: str,
    event_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> Response:
    return await controller.get_camera_event_snapshot(camera_id, event_id, service)


@router.get("/{camera_id}/health", response_model=CameraHealthResponse)
async def get_camera_health(
    camera_id: str,
    service: Annotated[LiveCameraService, Depends(get_live_camera_service)],
) -> dict:
    return await controller.get_camera_health(camera_id, service)
