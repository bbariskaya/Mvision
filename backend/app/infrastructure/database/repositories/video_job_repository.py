import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import VideoJob


class VideoJobRepository:
    _CLAIM_ADVISORY_LOCK_ID = 0x4D564944

    async def create(self, session: AsyncSession, job: VideoJob) -> VideoJob:
        session.add(job)
        await session.flush()
        return job

    async def get_by_id(self, session: AsyncSession, job_id: str) -> VideoJob | None:
        return await session.get(VideoJob, job_id)

    async def claim_next(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        lease_seconds: int,
        max_concurrent_jobs: int,
    ) -> VideoJob | None:
        await session.execute(
            select(func.pg_advisory_xact_lock(self._CLAIM_ADVISORY_LOCK_ID))
        )
        active_stmt = select(func.count()).select_from(VideoJob).where(
            VideoJob.status.in_(("processing", "cancelling")),
            VideoJob.lease_expires_at >= now,
        )
        active_count = (await session.execute(active_stmt)).scalar_one()
        if active_count >= max_concurrent_jobs:
            return None
        stmt = (
            select(VideoJob)
            .where(
                VideoJob.attempt_count < VideoJob.max_attempts,
                or_(
                    (VideoJob.status == "pending") & (VideoJob.available_at <= now),
                    (VideoJob.status == "processing") & (VideoJob.lease_expires_at < now),
                ),
            )
            .order_by(VideoJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = "processing"
        job.stage = "starting"
        job.worker_id = worker_id
        job.lease_token = lease_token
        job.lease_expires_at = now + datetime.timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or now
        await session.flush()
        return job

    async def settle_exhausted(
        self, session: AsyncSession, now: datetime.datetime
    ) -> list[tuple[str, str]]:
        stmt = (
            select(VideoJob)
            .where(
                VideoJob.status.in_(("processing", "cancelling")),
                VideoJob.lease_expires_at < now,
                VideoJob.attempt_count >= VideoJob.max_attempts,
            )
            .order_by(VideoJob.created_at)
            .with_for_update(skip_locked=True)
        )
        jobs = list((await session.execute(stmt)).scalars().all())
        settled: list[tuple[str, str]] = []
        for job in jobs:
            if job.status == "cancelling":
                job.status = "cancelled"
                job.stage = "cancelled"
                job.cancelled_at = now
            else:
                job.status = "failed"
                job.stage = "failed"
                job.error_code = "VIDEO_JOB_ATTEMPTS_EXHAUSTED"
                job.completed_at = now
            self._clear_lease(job)
            settled.append((job.process_id, job.status))
        if jobs:
            await session.flush()
        return settled

    async def lock_owned(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
    ) -> VideoJob | None:
        stmt = (
            select(VideoJob)
            .where(
                VideoJob.job_id == job_id,
                VideoJob.worker_id == worker_id,
                VideoJob.lease_token == lease_token,
                VideoJob.status.in_(("processing", "cancelling")),
                VideoJob.cancellation_requested.is_(False),
                VideoJob.lease_expires_at >= now,
            )
            .with_for_update()
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def renew_lease(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        expires_at: datetime.datetime,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if not self._owns_active_lease(
            job, worker_id, lease_token, datetime.datetime.now(datetime.UTC)
        ):
            return False
        assert job is not None
        job.lease_expires_at = expires_at
        await session.flush()
        return True

    async def update_progress(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        *,
        stage: str,
        progress_percent: float,
        processed_frames: int,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if not self._owns_active_lease(
            job, worker_id, lease_token, datetime.datetime.now(datetime.UTC)
        ):
            return False
        assert job is not None
        job.stage = stage
        job.progress_percent = max(0.0, min(100.0, progress_percent))
        job.processed_frames = max(job.processed_frames, processed_frames)
        await session.flush()
        return True

    async def request_cancel(self, session: AsyncSession, job_id: str) -> VideoJob | None:
        job = await session.get(VideoJob, job_id)
        if job is None:
            return None
        now = datetime.datetime.now(datetime.UTC)
        if job.status == "pending":
            job.cancellation_requested = True
            job.status = "cancelled"
            job.stage = "cancelled"
            job.cancelled_at = now
        elif job.status == "processing":
            job.cancellation_requested = True
            job.status = "cancelling"
            job.stage = "cancelling"
        await session.flush()
        return job

    async def complete(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        person_count: int,
        *,
        processed_frames: int,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.status = "completed"
        job.stage = "completed"
        job.progress_percent = 100.0
        job.person_count = person_count
        job.processed_frames = max(job.processed_frames, processed_frames)
        job.completed_at = datetime.datetime.now(datetime.UTC)
        self._clear_lease(job)
        await session.flush()
        return True

    async def fail(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        error_code: str,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.status = "failed"
        job.stage = "failed"
        job.error_code = error_code
        job.completed_at = datetime.datetime.now(datetime.UTC)
        self._clear_lease(job)
        await session.flush()
        return True

    async def mark_cancelled(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.status = "cancelled"
        job.stage = "cancelled"
        job.cancelled_at = datetime.datetime.now(datetime.UTC)
        self._clear_lease(job)
        await session.flush()
        return True

    async def release_for_retry(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        *,
        available_at: datetime.datetime,
        error_code: str,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.status = "pending"
        job.stage = "queued"
        job.available_at = available_at
        job.error_code = error_code
        self._clear_lease(job)
        await session.flush()
        return True

    async def claim_expired_sources(
        self, session: AsyncSession, now: datetime.datetime, limit: int
    ) -> list[VideoJob]:
        stmt = (
            select(VideoJob)
            .where(
                VideoJob.source_deleted_at.is_(None),
                VideoJob.source_retention_until <= now,
            )
            .order_by(VideoJob.source_retention_until)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    def _clear_lease(job: VideoJob) -> None:
        job.worker_id = None
        job.lease_token = None
        job.lease_expires_at = None

    @staticmethod
    def _owns_active_lease(
        job: VideoJob | None,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
    ) -> bool:
        return bool(
            job is not None
            and job.status in {"processing", "cancelling"}
            and job.worker_id == worker_id
            and job.lease_token == lease_token
            and job.lease_expires_at is not None
            and job.lease_expires_at >= now
        )
