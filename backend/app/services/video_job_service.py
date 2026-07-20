from typing import Any

from app.infrastructure.database.models import VideoJob
from app.infrastructure.database.repositories import VideoJobRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.services.exceptions import JobNotFoundError


class VideoJobService:
    def __init__(self, job_repo: VideoJobRepository):
        self._jobs = job_repo

    async def get(self, job_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            job = await self._jobs.get_by_id(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return self._snapshot(job)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            job = await self._jobs.request_cancel(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            await session.commit()
            return self._snapshot(job)

    @staticmethod
    def _snapshot(job: VideoJob) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "process_id": job.process_id,
            "status": job.status,
            "stage": job.stage,
            "progress_percent": job.progress_percent,
            "cancellation_requested": job.cancellation_requested,
            "error_code": job.error_code,
            "video": {
                "duration": job.duration_seconds,
                "fps": job.fps,
                "width": job.width,
                "height": job.height,
                "total_frames": job.total_frames,
                "processed_frames": job.processed_frames,
                "sampling": job.sampling,
                "source_available": job.source_deleted_at is None,
            },
            "person_count": job.person_count,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "cancelled_at": job.cancelled_at,
        }
