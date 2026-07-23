import asyncio
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
    ProcessEventRepository,
    ProcessRecordRepository,
    VideoJobRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.infrastructure.video.native_runner import (
    NativeVideoCancelledError,
    NativeVideoFailedError,
    NativeVideoRunner,
    NativeVideoTimeoutError,
)
from app.infrastructure.video.protocol import VideoEvent, VideoProgress, VideoTrackOutput
from app.services.video_result_service import (
    VideoFinalizationLeaseLostError,
    VideoFinalizationResult,
)

logger = logging.getLogger(__name__)


class VideoLeaseLostError(RuntimeError):
    pass


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


FinalizeCallback = Callable[
    [VideoJob, list[VideoTrackOutput], Path, str, str, int],
    Awaitable[VideoFinalizationResult],
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
        event_repo: ProcessEventRepository | None = None,
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
        self._events = event_repo
        self._session_factory = session_factory
        self._temp_root = temp_root

    async def process_one_job(self, worker_id: str) -> bool:
        lease_token = new_uuid7()
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            settled = await self._jobs.settle_exhausted(session, now)
            for process_id, status in settled:
                if status == "cancelled":
                    await self._processes.cancel(session, process_id)
                else:
                    await self._processes.fail(
                        session, process_id, "VIDEO_JOB_ATTEMPTS_EXHAUSTED"
                    )
            job = await self._jobs.claim_next(
                session,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now,
                lease_seconds=self._settings.video_job_lease_seconds,
                max_concurrent_jobs=self._settings.video_max_concurrent_jobs,
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
        lease_lost = asyncio.Event()
        lease_task = asyncio.create_task(
            self._renew_lease(job.job_id, worker_id, lease_token, lease_lost)
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
                    updated = await self._jobs.update_progress(
                        progress_session,
                        job.job_id,
                        worker_id,
                        lease_token,
                        stage="inference",
                        progress_percent=event.progress_percent,
                        processed_frames=event.processed_frames,
                    )
                    await progress_session.commit()
                    if not updated:
                        lease_lost.set()
                        raise VideoLeaseLostError("Video job lease was lost during progress")

            async def cancellation_requested() -> bool:
                if lease_lost.is_set():
                    return True
                async with self._session_factory() as check_session:
                    current = await self._jobs.get_by_id(check_session, job.job_id)
                    if (
                        current is None
                        or current.worker_id != worker_id
                        or current.lease_token != lease_token
                        or current.lease_expires_at is None
                        or current.lease_expires_at < datetime.now(UTC)
                    ):
                        lease_lost.set()
                        return True
                    return current.cancellation_requested

            native_completed = await self._runner.run(
                job, local_path, on_event, cancellation_requested
            )
            if lease_lost.is_set():
                return True
            finalized = await self._finalize(
                job,
                tracks,
                local_path,
                worker_id,
                lease_token,
                native_completed.processed_frames,
            )
            if lease_lost.is_set():
                return True
            await self._log_event(
                job.process_id,
                "video_job_completed",
                {
                    "job_id": job.job_id,
                    "person_count": finalized.person_count,
                    "faces": list(finalized.faces),
                },
            )
            return True
        except NativeVideoCancelledError:
            if lease_lost.is_set():
                return True
            async with self._session_factory() as session:
                cancelled = await self._jobs.mark_cancelled(
                    session, job.job_id, worker_id, lease_token
                )
                if cancelled:
                    await self._processes.cancel(session, job.process_id)
                await session.commit()
            if cancelled:
                await self._log_event(
                    job.process_id, "video_job_cancelled", {"job_id": job.job_id}
                )
            return True
        except (VideoLeaseLostError, VideoFinalizationLeaseLostError):
            return True
        except (NativeVideoTimeoutError, NativeVideoFailedError) as exc:
            if lease_lost.is_set():
                return True
            await self._handle_failure(job, worker_id, lease_token, exc.error_code)
            return True
        except Exception:
            if lease_lost.is_set():
                return True
            logger.exception("Video job %s failed during processing", job.job_id)
            await self._handle_failure(
                job, worker_id, lease_token, "VIDEO_PIPELINE_ERROR"
            )
            return True
        finally:
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _handle_failure(
        self, job: VideoJob, worker_id: str, lease_token: str, error_code: str
    ) -> None:
        terminal = False
        async with self._session_factory() as session:
            if job.attempt_count >= job.max_attempts:
                terminal = await self._jobs.fail(
                    session,
                    job.job_id,
                    worker_id,
                    lease_token,
                    error_code,
                )
                if terminal:
                    await self._processes.fail(session, job.process_id, error_code)
            else:
                await self._jobs.release_for_retry(
                    session,
                    job.job_id,
                    worker_id,
                    lease_token,
                    available_at=datetime.now(UTC) + timedelta(seconds=30),
                    error_code=error_code,
                )
            await session.commit()
        if terminal:
            await self._log_event(
                job.process_id,
                "video_job_failed",
                {"job_id": job.job_id, "error_code": error_code},
            )

    async def _log_event(
        self, process_id: str, event_type: str, details: dict[str, Any]
    ) -> None:
        if self._events is None:
            return
        try:
            async with self._session_factory() as session:
                await self._events.create(session, process_id, event_type, details)
                await session.commit()
        except Exception:
            logger.warning("Failed to persist %s event for %s", event_type, process_id)

    async def _renew_lease(
        self,
        job_id: str,
        worker_id: str,
        lease_token: str,
        lease_lost: asyncio.Event,
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
                lease_lost.set()
                return
