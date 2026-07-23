from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.presentation.auth import require_live_api_key
from app.presentation.dependencies import get_live_session_service
from app.presentation.schemas.live_sessions import (
    LiveCapabilitiesResponse,
    LiveSessionCreateRequest,
    LiveSessionListResponse,
    LiveSessionReconfigureRequest,
    LiveSessionResponse,
)
from app.services.live_session_service import LiveSessionService

router = APIRouter(
    prefix="/api/v1/live",
    tags=["live sessions"],
    dependencies=[Depends(require_live_api_key)],
)


@router.get("/capabilities", response_model=LiveCapabilitiesResponse)
async def get_live_capabilities(
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return service.capabilities()


@router.post(
    "/sessions",
    response_model=LiveSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_live_session(
    request: LiveSessionCreateRequest,
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return await service.create(request)


@router.get("/sessions", response_model=LiveSessionListResponse)
async def list_live_sessions(
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return await service.list()


@router.get("/sessions/{session_id}", response_model=LiveSessionResponse)
async def get_live_session(
    session_id: UUID,
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return await service.get(str(session_id))


@router.post("/sessions/{session_id}/reconfigure", response_model=LiveSessionResponse)
async def reconfigure_live_session(
    session_id: UUID,
    request: LiveSessionReconfigureRequest,
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return await service.reconfigure(str(session_id), request)


@router.post("/sessions/{session_id}/stop", response_model=LiveSessionResponse)
async def stop_live_session(
    session_id: UUID,
    service: Annotated[LiveSessionService, Depends(get_live_session_service)],
) -> dict:
    return await service.stop(str(session_id))
