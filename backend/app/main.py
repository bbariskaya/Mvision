from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.presentation.dependencies import get_container
from app.presentation.routers.faces import router as faces_router
from app.presentation.routers.health import router as health_router
from app.presentation.routers.processes import router as processes_router
from app.presentation.routers.videos import router as videos_router
from app.services.exceptions import add_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    app.state.settings = settings
    container = get_container()
    await container.minio.ensure_bucket()
    await container.qdrant.setup()
    yield


app = FastAPI(
    title="MergenVision API",
    description="Phase 1 Face Recognition API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router, tags=["health"])
app.include_router(faces_router)
app.include_router(processes_router)
app.include_router(videos_router)

add_exception_handlers(app)
