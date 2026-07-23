from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.observability.metrics import create_metrics
from app.observability.telemetry import configure_telemetry
from app.presentation.dependencies import get_container
from app.presentation.routers.cameras import router as cameras_router
from app.presentation.routers.faces import router as faces_router
from app.presentation.routers.health import router as health_router
from app.presentation.routers.live_connectors import router as live_connectors_router
from app.presentation.routers.live_sessions import router as live_sessions_router
from app.presentation.routers.metrics import router as metrics_router
from app.presentation.routers.processes import router as processes_router
from app.presentation.routers.videos import router as videos_router
from app.services.exceptions import add_exception_handlers

settings = get_settings()
telemetry = configure_telemetry(settings)
metrics = create_metrics()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.settings = settings
    container = get_container()
    await container.minio.ensure_bucket()
    await container.qdrant.setup()
    try:
        yield
    finally:
        await container.mediamtx_client.aclose()
        timeout_millis = int(settings.otel_shutdown_timeout_seconds * 1_000)
        app.state.telemetry.shutdown(timeout_millis)


app = FastAPI(
    title="MergenVision API",
    description="GPU-accelerated image, video, and livestream face recognition API",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.telemetry = telemetry
app.state.metrics = metrics
telemetry.install_http_middleware(app)

app.include_router(health_router, tags=["health"])
app.include_router(metrics_router)
app.include_router(faces_router)
app.include_router(processes_router)
app.include_router(videos_router)
app.include_router(cameras_router)
app.include_router(live_sessions_router)
app.include_router(live_connectors_router)

add_exception_handlers(app)
