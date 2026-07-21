import asyncio
import logging
import os
import socket

from app.presentation.dependencies import get_container

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def main() -> None:
    container = get_container()
    worker_id = os.getenv("VIDEO_WORKER_ID", f"video-{socket.gethostname()}")
    await container.minio.ensure_bucket()
    await container.qdrant.setup()
    logger.info("Video worker %s started", worker_id)
    while True:
        processed = await container.video_processor.process_one_job(worker_id)
        if not processed:
            await container.video_jobs.cleanup_expired_sources()
            await asyncio.sleep(container.settings.video_worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
