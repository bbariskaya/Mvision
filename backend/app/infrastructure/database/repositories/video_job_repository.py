import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import VideoJob


class VideoJobRepository:
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
    ) -> VideoJob | None:
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

    async def renew_lease(
        self,
        session: AsyncSession,
        job_id: str,
        worker_id: str,
        lease_token: str,
        expires_at: datetime.datetime,
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
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
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.stage = stage
        job.progress_percent = max(0.0, min(100.0, progress_percent))
        job.processed_frames = max(job.processed_frames, processed_frames)
        await session.flush()
        return True

    async def request_cancel(self, session: AsyncSession, job_id: str) -> VideoJob | None:
        job = await session.get(VideoJob, job_id)
        if job is None:
            return None
        job.cancellation_requested = True
        now = datetime.datetime.now(datetime.UTC)
        if job.status == "pending":
            job.status = "cancelled"
            job.stage = "cancelled"
            job.cancelled_at = now
        elif job.status == "processing":
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
    ) -> bool:
        job = await session.get(VideoJob, job_id)
        if job is None or job.worker_id != worker_id or job.lease_token != lease_token:
            return False
        job.status = "completed"
        job.stage = "completed"
        job.progress_percent = 100.0
        job.person_count = person_count
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
