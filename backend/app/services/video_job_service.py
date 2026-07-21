import re
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, Protocol

from app.infrastructure.database.models import VideoJob
from app.infrastructure.database.repositories import VideoJobRepository, VideoTrackRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter
from app.services.exceptions import JobNotFoundError, ServiceError, VideoError


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class VideoJobService:
    def __init__(
        self,
        job_repo: VideoJobRepository,
        track_repo: VideoTrackRepository,
        minio: MinIOAdapter,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
    ):
        self._jobs = job_repo
        self._tracks = track_repo
        self._minio = minio
        self._session_factory = session_factory

    async def get(self, job_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            job = await self._jobs.get_by_id(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return self._snapshot(job)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            job = await self._jobs.request_cancel(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            await session.commit()
            return self._snapshot(job)

    async def result(self, job_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            job = await self._jobs.get_by_id(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            if job.status != "completed":
                raise ServiceError(
                    "Video job has not completed",
                    "Video job result is not available yet.",
                    "JOB_NOT_COMPLETED",
                    409,
                    job.process_id,
                )
            tracks = await self._tracks.list_by_job(session, job_id)
            snapshot = self._snapshot(job)
            return {
                "job_id": job.job_id,
                "process_id": job.process_id,
                "status": job.status,
                "video": snapshot["video"],
                "person_count": len(tracks),
                "persons": [
                    {
                        "face_id": track.face_id,
                        "track_id": track.track_id,
                        "status": track.status_snapshot,
                        "name": track.name_snapshot
                        if track.status_snapshot == "known"
                        else None,
                        "metadata": track.metadata_snapshot
                        if track.status_snapshot == "known"
                        else {},
                        "first_seen": track.first_seen,
                        "last_seen": track.last_seen,
                        "total_duration": track.total_duration,
                        "confidence": track.match_confidence,
                        "appearances": track.appearances,
                        "detections": track.detections,
                    }
                    for track in tracks
                ],
            }

    async def source(self, job_id: str, range_header: str | None) -> dict[str, Any]:
        async with self._session_factory() as session:
            job = await self._jobs.get_by_id(session, job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            if job.source_deleted_at is not None:
                raise VideoError("Retained source video has expired", "VIDEO_EXPIRED", 410)
            total = job.source_size
            offset, end = self._parse_range(range_header, total)
            data = await self._minio.read_video_range(
                job.source_object_key, offset, end - offset + 1
            )
            partial = range_header is not None
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(data)),
            }
            if partial:
                headers["Content-Range"] = f"bytes {offset}-{end}/{total}"
            return {
                "data": data,
                "content_type": job.source_content_type,
                "status_code": 206 if partial else 200,
                "headers": headers,
            }

    async def appearances(self, face_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            tracks = await self._tracks.list_by_face(session, face_id)
            values = []
            for track in tracks:
                job = await self._jobs.get_by_id(session, track.job_id)
                if job is None:
                    continue
                values.append(
                    {
                        "job_id": job.job_id,
                        "track_id": track.track_id,
                        "first_seen": track.first_seen,
                        "last_seen": track.last_seen,
                        "intervals": track.appearances,
                        "source_available": job.source_deleted_at is None,
                        "created_at": job.created_at,
                    }
                )
            return {"face_id": face_id, "appearances": values}

    async def cleanup_expired_sources(self, limit: int = 25) -> int:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            jobs = await self._jobs.claim_expired_sources(session, now, limit)
            deleted = 0
            for job in jobs:
                await self._minio.delete_video(job.source_object_key)
                job.source_deleted_at = now
                deleted += 1
            await session.commit()
            return deleted

    @staticmethod
    def _parse_range(value: str | None, total: int) -> tuple[int, int]:
        if value is None:
            return 0, total - 1
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        if match is None or (not match.group(1) and not match.group(2)):
            raise VideoError("Invalid video byte range", "INVALID_RANGE", 416)
        if not match.group(1):
            length = int(match.group(2))
            offset = max(0, total - length)
            end = total - 1
        else:
            offset = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else total - 1
        if offset < 0 or offset >= total or end < offset:
            raise VideoError("Invalid video byte range", "INVALID_RANGE", 416)
        return offset, min(end, total - 1)

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
