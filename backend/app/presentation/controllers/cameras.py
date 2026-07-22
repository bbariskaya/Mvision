from uuid import UUID

from fastapi import Response

from app.presentation.schemas.cameras import CameraCreateRequest
from app.services.exceptions import LiveCameraError
from app.services.live_camera_service import LiveCameraService


def _uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise LiveCameraError(f"{field} must be a valid UUID", "INVALID_ID", 422) from exc


async def register_camera(
    request: CameraCreateRequest, service: LiveCameraService
) -> dict:
    return await service.register(
        request.name,
        request.rtsp_uri.get_secret_value(),
    )


async def list_cameras(service: LiveCameraService) -> dict:
    return {"cameras": await service.list()}


async def get_camera(camera_id: str, service: LiveCameraService) -> dict:
    return await service.get(_uuid(camera_id, "cameraId"))


async def start_camera(
    camera_id: str,
    service: LiveCameraService,
    *,
    traceparent: str | None = None,
    tracestate: str | None = None,
) -> dict:
    return await service.start(
        _uuid(camera_id, "cameraId"), traceparent=traceparent, tracestate=tracestate
    )


async def stop_camera(camera_id: str, service: LiveCameraService) -> dict:
    return await service.stop(_uuid(camera_id, "cameraId"))


async def delete_camera(camera_id: str, service: LiveCameraService) -> dict:
    return await service.delete(_uuid(camera_id, "cameraId"))


async def list_camera_events(
    camera_id: str, limit: int, service: LiveCameraService
) -> dict:
    return await service.events(_uuid(camera_id, "cameraId"), limit)


async def get_camera_health(camera_id: str, service: LiveCameraService) -> dict:
    return await service.health(_uuid(camera_id, "cameraId"))


async def get_camera_event_snapshot(
    camera_id: str, event_id: str, service: LiveCameraService
) -> Response:
    snapshot = await service.snapshot(
        _uuid(camera_id, "cameraId"),
        _uuid(event_id, "eventId"),
    )
    return Response(content=snapshot["data"], media_type=snapshot["media_type"])
