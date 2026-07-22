import asyncio
import logging
import os
import signal
import socket

from app.presentation.dependencies import get_container
from app.services.live_supervisor import LiveSupervisor

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def run_worker(
    supervisor: LiveSupervisor,
    worker_id: str,
    poll_seconds: float,
    shutdown: asyncio.Event,
) -> None:
    while not shutdown.is_set():
        processed = await supervisor.process_one_camera(worker_id)
        if not processed and not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


async def main() -> None:
    container = get_container()
    supervisor = container.live_supervisor
    worker_id = os.getenv("LIVE_WORKER_ID", f"live-{socket.gethostname()}")
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        supervisor.request_stop()
        shutdown.set()

    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(selected_signal, request_shutdown)
    logger.info("Live worker %s started", worker_id)
    await run_worker(
        supervisor, worker_id, container.settings.live_worker_poll_seconds, shutdown
    )


if __name__ == "__main__":
    asyncio.run(main())
