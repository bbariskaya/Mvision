from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.presentation.routers.health import router as health_router
from app.services.exceptions import add_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    app.state.settings = settings
    yield


app = FastAPI(
    title="MergenVision API",
    description="Phase 1 Face Recognition API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router, tags=["health"])

add_exception_handlers(app)
