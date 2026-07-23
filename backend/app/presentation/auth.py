import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

live_api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="LiveApiKey",
    auto_error=False,
)


async def require_live_api_key(
    request: Request,
    supplied: Annotated[str | None, Security(live_api_key_header)] = None,
) -> None:
    configured = request.app.state.settings.live_api_key
    if (
        configured is None
        or supplied is None
        or not secrets.compare_digest(supplied, configured.get_secret_value())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "LIVE_API_KEY_INVALID"},
        )
