from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.presentation.dependencies import get_process_service
from app.presentation.schemas.processes import ProcessResponse
from app.services.exceptions import ValidationError
from app.services.process_query_service import ProcessQueryService

router = APIRouter(prefix="/api/v1/processes", tags=["processes"])


@router.get("/{process_id}", response_model=ProcessResponse)
async def get_process(
    process_id: str,
    service: Annotated[ProcessQueryService, Depends(get_process_service)],
) -> dict:
    try:
        validated = str(UUID(process_id))
    except ValueError as exc:
        raise ValidationError("processId must be a valid UUID", "INVALID_ID") from exc
    return await service.get(validated)
