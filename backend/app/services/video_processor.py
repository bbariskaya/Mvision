import asyncio
import inspect
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.models import VideoJob
from app.infrastructure.database.repositories import (
    ProcessRecordRepository,
    VideoJobRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.video.native_runner import NativeVideoCancelledError, NativeVideoRunner
from app.infrastructure.video.protocol import VideoEvent, VideoProgress, VideoTrackOutput

logger = logging.getLogger(__name__)


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


FinalizeCallback = Callable[
    [VideoJob, list[VideoTrackOutput], Path], Awaitable[int] | int
]


class VideoJobProcessor:
    def __init__(
        self,
        settings: Settings,
        minio: MinIOAdapter,
        job_repo: VideoJobRepository,
        process_repo: ProcessRecordRepository,
        runner: NativeVideoRunner,
        finalize: FinalizeCallback,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
        temp_root: Path | None = None,
    ):
        self._settings = settings
        self._minio = minio
        self._jobs = job_repo
        self._processes = process_repo
        self._runner = runner
        self._finalize = finalize
        self._session_factory = session_factory
        self._temp_root = temp_root

    async def process_one_job(self, worker_id: str) -> bool:
        lease_token = new_uuid7()
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await self._jobs.claim_next(
                session,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now,
                lease_seconds=self._settings.video_job_lease_seconds,
            )
            await session.commit()
        if job is None:
            return False

        work_dir = Path(
            tempfile.mkdtemp(prefix=f"mvision-{job.job_id}-", dir=self._temp_root)
        )
        local_path = work_dir / "source"
        tracks: list[VideoTrackOutput] = []
        last_progress_update = 0.0
        lease_task = asyncio.create_task(
            self._renew_lease(job.job_id, worker_id, lease_token)
        )
        try:
            await self._minio.download_video(job.source_object_key, local_path)

            async def on_event(event: VideoEvent) -> None:
                nonlocal last_progress_update
                if isinstance(event, VideoTrackOutput):
                    tracks.append(event)
                    return
                if not isinstance(event, VideoProgress):
                    return
                current = time.monotonic()
                if (
                    last_progress_update != 0.0
                    and current - last_progress_update
                    < self._settings.video_progress_update_interval_seconds
                ):
                    return
                last_progress_update = current
                async with self._session_factory() as progress_session:
                    await self._jobs.update_progress(
                        progress_session,
                        job.job_id,
                        worker_id,
                        lease_token,
                        stage="inference",
                        progress_percent=event.progress_percent,
                        processed_frames=event.processed_frames,
                    )
                    await progress_session.commit()

            async def cancellation_requested() -> bool:
                async with self._session_factory() as check_session:
                    current = await self._jobs.get_by_id(check_session, job.job_id)
                    return current is None or current.cancellation_requested

            native_completed = await self._runner.run(
                job, local_path, on_event, cancellation_requested
            )
            result = self._finalize(job, tracks, local_path)
            person_count = await result if inspect.isawaitable(result) else result
            async with self._session_factory() as session:
                completed = await self._jobs.complete(
                    session,
                    job.job_id,
                    worker_id,
                    lease_token,
                    person_count,
                    processed_frames=native_completed.processed_frames,
                )
                if not completed:
                    raise RuntimeError("Video job lease was lost before completion")
                await self._processes.complete(session, job.process_id, person_count)
                await session.commit()
            return True
        except NativeVideoCancelledError:
            async with self._session_factory() as session:
                await self._jobs.mark_cancelled(
                    session, job.job_id, worker_id, lease_token
                )
                await self._processes.cancel(session, job.process_id)
                await session.commit()
            return True
        except Exception:
            logger.exception("Video job %s failed during processing", job.job_id)
            async with self._session_factory() as session:
                if job.attempt_count >= job.max_attempts:
                    await self._jobs.fail(
                        session,
                        job.job_id,
                        worker_id,
                        lease_token,
                        "VIDEO_PIPELINE_ERROR",
                    )
                    await self._processes.fail(
                        session, job.process_id, "VIDEO_PIPELINE_ERROR"
                    )
                else:
                    await self._jobs.release_for_retry(
                        session,
                        job.job_id,
                        worker_id,
                        lease_token,
                        available_at=datetime.now(UTC) + timedelta(seconds=30),
                        error_code="VIDEO_PIPELINE_ERROR",
                    )
                await session.commit()
            return True
        finally:
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _renew_lease(
        self, job_id: str, worker_id: str, lease_token: str
    ) -> None:
        interval = max(1.0, self._settings.video_job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            expires_at = datetime.now(UTC) + timedelta(
                seconds=self._settings.video_job_lease_seconds
            )
            async with self._session_factory() as session:
                renewed = await self._jobs.renew_lease(
                    session, job_id, worker_id, lease_token, expires_at
                )
                await session.commit()
            if not renewed:
                return
