import asyncio
import hashlib
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import UploadFile

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
from app.infrastructure.video.probe import VideoMetadata, VideoProbeError, probe_video
from app.services.exceptions import ValidationError, VideoError

logger = logging.getLogger(__name__)


def resolve_sampling(
    settings: Settings,
    source_fps: float,
    mode: str | None = None,
    every_n_frames: int | None = None,
    frames_per_second: float | None = None,
) -> dict[str, Any]:
    selected_mode = mode or settings.video_default_sampling_mode
    if selected_mode == "every_frame":
        if every_n_frames is not None or frames_per_second is not None:
            raise ValidationError("every_frame takes no sampling value", "INVALID_SAMPLING")
        every_n = 1
        requested_fps = source_fps
    elif selected_mode == "every_n_frames":
        if every_n_frames is None or every_n_frames <= 0 or frames_per_second is not None:
            raise ValidationError(
                "every_n_frames requires a positive everyNFrames", "INVALID_SAMPLING"
            )
        every_n = every_n_frames
        requested_fps = source_fps / every_n
    elif selected_mode == "frames_per_second":
        requested_fps = (
            frames_per_second
            if frames_per_second is not None
            else settings.video_default_frames_per_second
        )
        if every_n_frames is not None or requested_fps <= 0 or requested_fps > source_fps:
            raise ValidationError(
                "frames_per_second must be positive and no greater than source FPS",
                "INVALID_SAMPLING",
            )
        every_n = max(1, round(source_fps / requested_fps))
    else:
        raise ValidationError("Unsupported sampling mode", "INVALID_SAMPLING")
    return {
        "mode": selected_mode,
        "requestedFramesPerSecond": requested_fps,
        "everyNFrames": every_n,
        "effectiveFramesPerSecond": source_fps / every_n,
    }


class VideoUploadService:
    def __init__(
        self,
        settings: Settings,
        minio: MinIOAdapter,
        job_repo: VideoJobRepository,
        process_repo: ProcessRecordRepository,
        event_repo: ProcessEventRepository,
    ):
        self._settings = settings
        self._minio = minio
        self._jobs = job_repo
        self._processes = process_repo
        self._events = event_repo

    async def submit(
        self,
        video: UploadFile,
        sampling_mode: str | None,
        every_n_frames: int | None,
        frames_per_second: float | None,
        process_id: str | None = None,
    ) -> dict[str, Any]:
        process_id = process_id or new_uuid7()
        async with AsyncSessionLocal() as session:
            await self._processes.create(session, process_id, "video_recognize")
            await session.commit()

        temp_path: Path | None = None
        object_key: str | None = None
        try:
            temp_path, size, sha256 = await self._stream_upload(video)
            metadata = await probe_video(temp_path, self._settings.video_probe_timeout_seconds)
            self._validate_metadata(metadata)
            sampling = resolve_sampling(
                self._settings,
                metadata.fps,
                sampling_mode,
                every_n_frames,
                frames_per_second,
            )
            job_id = new_uuid7()
            object_key = f"{self._settings.video_minio_prefix}/{job_id}/source"
            content_type = self._content_type(metadata)
            stat = await self._minio.upload_video(
                object_key, temp_path, content_type, sha256
            )
            if stat.size != size:
                raise VideoError("Stored video size does not match upload", "VIDEO_INVALID")
            now = datetime.now(UTC)
            job = VideoJob(
                job_id=job_id,
                process_id=process_id,
                status="pending",
                stage="queued",
                progress_percent=0.0,
                cancellation_requested=False,
                attempt_count=0,
                max_attempts=self._settings.video_job_max_attempts,
                available_at=now,
                source_bucket=stat.bucket,
                source_object_key=object_key,
                source_content_type=content_type,
                source_size=size,
                source_sha256=sha256,
                source_retention_until=now
                + timedelta(seconds=self._settings.video_retention_seconds),
                container_format=metadata.container,
                video_codec=metadata.codec,
                duration_seconds=metadata.duration_seconds,
                fps=metadata.fps,
                width=metadata.width,
                height=metadata.height,
                total_frames=metadata.total_frames,
                processed_frames=0,
                person_count=0,
                sampling=sampling,
            )
            async with AsyncSessionLocal() as session:
                await self._jobs.create(session, job)
                process = await self._processes.get_by_id(session, process_id)
                if process is not None:
                    process.details = {
                        "job_id": job_id,
                        "video": self._metadata_dict(metadata),
                        "sampling": sampling,
                    }
                await self._events.create(
                    session,
                    process_id,
                    "video_job_created",
                    {"job_id": job_id, "size": size, "sampling": sampling},
                )
                await session.commit()
            return {
                "job_id": job_id,
                "process_id": process_id,
                "status": "pending",
                "status_url": f"/api/v1/videos/jobs/{job_id}",
                "result_url": f"/api/v1/videos/jobs/{job_id}/result",
            }
        except VideoProbeError as exc:
            await self._fail_process(process_id, exc.code)
            raise VideoError(str(exc), exc.code, process_id=process_id) from exc
        except (ValidationError, VideoError) as exc:
            exc.process_id = process_id
            await self._fail_process(process_id, exc.error_code)
            raise
        except Exception as exc:
            logger.exception("Video upload process %s failed", process_id)
            await self._fail_process(process_id, "VIDEO_INVALID")
            raise VideoError(
                "Video upload failed", "VIDEO_INVALID", process_id=process_id
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if object_key is not None and not await self._job_exists_for_object(object_key):
                try:
                    await self._minio.delete_video(object_key)
                except Exception:
                    logger.exception("Failed to remove partial video object %s", object_key)

    async def _stream_upload(self, video: UploadFile) -> tuple[Path, int, str]:
        temp = tempfile.NamedTemporaryFile(prefix="mvision-video-", suffix=".upload", delete=False)
        path = Path(temp.name)
        temp.close()
        size = 0
        digest = hashlib.sha256()
        try:
            with path.open("wb") as output:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > self._settings.video_max_upload_bytes:
                        raise VideoError(
                            "Video exceeds maximum upload size", "VIDEO_TOO_LARGE", 413
                        )
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            if size == 0:
                raise VideoError("Video is empty", "VIDEO_EMPTY")
            return path, size, digest.hexdigest()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _validate_metadata(self, metadata: VideoMetadata) -> None:
        if metadata.container not in self._settings.video_allowed_container_set:
            raise VideoError("Unsupported video container", "VIDEO_UNSUPPORTED_CONTAINER", 415)
        if metadata.codec not in self._settings.video_allowed_codec_set:
            raise VideoError("Unsupported video codec", "VIDEO_UNSUPPORTED_CODEC", 415)
        if metadata.duration_seconds > self._settings.video_max_duration_seconds:
            raise VideoError("Video duration exceeds configured limit", "VIDEO_DURATION_EXCEEDED")

    async def _fail_process(self, process_id: str, error_code: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                await self._processes.fail(session, process_id, error_code)
                await self._events.create(
                    session, process_id, "video_upload_failed", {"error_code": error_code}
                )
                await session.commit()
        except Exception:
            logger.exception("Failed to persist upload failure for %s", process_id)

    async def _job_exists_for_object(self, object_key: str) -> bool:
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(VideoJob.job_id).where(VideoJob.source_object_key == object_key)
            )
            return result.scalar_one_or_none() is not None

    @staticmethod
    def _content_type(metadata: VideoMetadata) -> str:
        return {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
            "matroska": "video/x-matroska",
        }[metadata.container]

    @staticmethod
    def _metadata_dict(metadata: VideoMetadata) -> dict[str, Any]:
        return {
            "duration": metadata.duration_seconds,
            "fps": metadata.fps,
            "width": metadata.width,
            "height": metadata.height,
            "total_frames": metadata.total_frames,
            "container": metadata.container,
            "codec": metadata.codec,
        }
