import asyncio
import logging
import os
import socket

from app.presentation.dependencies import ServiceContainer, get_container

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def run_iteration(container: ServiceContainer, worker_id: str) -> None:
    processed = await container.video_processor.process_one_job(worker_id)
    await container.video_jobs.cleanup_expired_sources()
    if not processed:
        await asyncio.sleep(container.settings.video_worker_poll_seconds)


async def main() -> None:
    container = get_container()
    worker_id = os.getenv("VIDEO_WORKER_ID", f"video-{socket.gethostname()}")
    await container.minio.ensure_bucket()
    await container.qdrant.setup()
    logger.info("Video worker %s started", worker_id)
    while True:
        await run_iteration(container, worker_id)


if __name__ == "__main__":
    asyncio.run(main())
