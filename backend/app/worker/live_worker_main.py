import asyncio
import logging
import os
import signal
import socket

from prometheus_client import start_http_server

from app.config import get_settings
from app.observability.metrics import create_metrics
from app.observability.telemetry import configure_telemetry
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
    settings = get_settings()
    worker_id = os.getenv("LIVE_WORKER_ID", f"live-{socket.gethostname()}")
    telemetry_settings = settings.model_copy(
        update={
            "otel_service_name": "mvision-live-worker",
            "otel_service_instance_id": worker_id,
        }
    )
    telemetry = configure_telemetry(telemetry_settings)
    metrics = create_metrics()
    metrics_server = None
    metrics_thread = None
    try:
        metrics_server, metrics_thread = start_http_server(
            settings.live_metrics_port,
            addr=settings.live_metrics_host,
            registry=metrics.registry,
        )
        metrics.set("worker_up", 1)
    except Exception:
        logger.warning("Metrics endpoint startup failed; worker processing continues")
    try:
        container = get_container(telemetry, metrics)
        supervisor = container.live_supervisor
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
    finally:
        metrics.set("worker_up", 0)
        try:
            if metrics_server is not None:
                metrics_server.shutdown()
                metrics_server.server_close()
            if metrics_thread is not None:
                metrics_thread.join(timeout=settings.otel_shutdown_timeout_seconds)
        except Exception:
            logger.warning("Metrics endpoint shutdown failed; worker exit continues")
        try:
            telemetry.shutdown(int(settings.otel_shutdown_timeout_seconds * 1_000))
        except Exception:
            logger.warning("Telemetry shutdown failed; worker exit continues")


if __name__ == "__main__":
    asyncio.run(main())
