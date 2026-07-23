from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.presentation.auth import require_live_api_key
from app.presentation.dependencies import get_live_connector_service
from app.presentation.schemas.live_connectors import (
    LiveConnectorCreateRequest,
    LiveConnectorListResponse,
    LiveConnectorResponse,
)
from app.services.live_connector_service import LiveConnectorService

router = APIRouter(
    prefix="/api/v1/live/connectors",
    tags=["live connectors"],
    dependencies=[Depends(require_live_api_key)],
)


@router.post("", response_model=LiveConnectorResponse, status_code=status.HTTP_201_CREATED)
async def create_live_connector(
    request: LiveConnectorCreateRequest,
    service: Annotated[LiveConnectorService, Depends(get_live_connector_service)],
) -> dict:
    return await service.create(request)


@router.get("", response_model=LiveConnectorListResponse)
async def list_live_connectors(
    service: Annotated[LiveConnectorService, Depends(get_live_connector_service)],
) -> dict:
    return await service.list()


@router.get("/{connector_id}", response_model=LiveConnectorResponse)
async def get_live_connector(
    connector_id: UUID,
    service: Annotated[LiveConnectorService, Depends(get_live_connector_service)],
) -> dict:
    return await service.get(str(connector_id))


@router.delete("/{connector_id}", response_model=LiveConnectorResponse)
async def delete_live_connector(
    connector_id: UUID,
    service: Annotated[LiveConnectorService, Depends(get_live_connector_service)],
) -> dict:
    return await service.delete(str(connector_id))
