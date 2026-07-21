import asyncio
import inspect
import logging
import struct
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.config import Settings
from app.infrastructure.database.models import VideoJob
from app.infrastructure.video.protocol import (
    HEADER_SIZE,
    MAX_EVENT_BYTES,
    VideoCompleted,
    VideoEvent,
    VideoFailed,
    decode_video_event,
)

logger = logging.getLogger(__name__)


class NativeVideoCancelledError(RuntimeError):
    pass


EventHandler = Callable[[VideoEvent], Awaitable[None] | None]
CancellationCheck = Callable[[], Awaitable[bool] | bool]


class NativeVideoRunner:
    def __init__(self, settings: Settings, poll_seconds: float = 0.1):
        self._settings = settings
        self._poll_seconds = poll_seconds

    async def run(
        self,
        job: VideoJob,
        local_path: Path,
        on_event: EventHandler,
        cancellation_requested: CancellationCheck,
    ) -> VideoCompleted:
        every_n = int(job.sampling.get("everyNFrames", 1))
        process = await asyncio.create_subprocess_exec(
            self._settings.video_native_executable,
            str(local_path),
            str(self._settings.video_worker_gpu_id),
            str(every_n),
            str(job.width),
            str(job.height),
            str(job.total_frames),
            str(job.fps),
            self._settings.video_tracker_config_path,
            self._settings.video_pgie_config_path,
            self._settings.video_preprocess_config_path,
            self._settings.video_sgie_config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(self._drain_stderr(process))
        events_task = asyncio.create_task(self._read_events(process, on_event))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.video_job_timeout_seconds
        try:
            while not events_task.done():
                if await self._resolve_bool(cancellation_requested()):
                    await self._terminate(process)
                    events_task.cancel()
                    await asyncio.gather(events_task, return_exceptions=True)
                    raise NativeVideoCancelledError("Video job cancellation requested")
                if loop.time() >= deadline:
                    await self._terminate(process)
                    events_task.cancel()
                    await asyncio.gather(events_task, return_exceptions=True)
                    raise TimeoutError("Video native worker timed out")
                await asyncio.sleep(self._poll_seconds)
            completed = await events_task
            return_code = await process.wait()
            if return_code != 0:
                if return_code == 3:
                    raise NativeVideoCancelledError("Native video worker cancelled")
                raise RuntimeError(f"Native video worker exited with code {return_code}")
            if completed is None:
                raise RuntimeError("Native video worker exited without a completed event")
            return completed
        finally:
            if process.returncode is None:
                await self._terminate(process)
            await stderr_task

    async def _read_events(
        self, process: asyncio.subprocess.Process, on_event: EventHandler
    ) -> VideoCompleted | None:
        if process.stdout is None:
            raise RuntimeError("Native video worker stdout is unavailable")
        completed: VideoCompleted | None = None
        while True:
            try:
                header = await process.stdout.readexactly(HEADER_SIZE)
            except asyncio.IncompleteReadError as exc:
                if not exc.partial:
                    break
                raise ValueError("TRUNCATED_FRAME") from exc
            payload_size = struct.unpack("!I", header)[0]
            if payload_size > MAX_EVENT_BYTES:
                raise ValueError("FRAME_TOO_LARGE")
            payload = await process.stdout.readexactly(payload_size)
            event = decode_video_event(header + payload)
            if isinstance(event, VideoFailed):
                raise RuntimeError(f"{event.error_code}: {event.message}")
            callback_result = on_event(event)
            if inspect.isawaitable(callback_result):
                await callback_result
            if isinstance(event, VideoCompleted):
                completed = event
        return completed

    @staticmethod
    async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        while line := await process.stderr.readline():
            logger.info("native-video: %s", line.decode(errors="replace").strip()[:1000])

    @staticmethod
    async def _resolve_bool(value: Awaitable[bool] | bool) -> bool:
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()
