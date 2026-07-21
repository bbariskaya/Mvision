from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.database.models import VideoJob
from app.services.video_job_service import VideoJobService


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        self.committed = True


class _Jobs:
    def __init__(self, jobs):
        self.jobs = jobs

    async def claim_expired_sources(self, session, now, limit):
        assert limit == 10
        return self.jobs


class _Tracks:
    pass


class _Minio:
    def __init__(self):
        self.deleted = []

    async def delete_video(self, object_key):
        self.deleted.append(object_key)


def _job() -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        job_id="019f8000-0000-7000-8000-000000000001",
        process_id="019f8000-0000-7000-8000-000000000002",
        status="completed",
        stage="completed",
        progress_percent=100,
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        source_bucket="videos",
        source_object_key="videos/019f8000-0000-7000-8000-000000000001/source",
        source_content_type="video/mp4",
        source_size=5,
        source_sha256="0" * 64,
        source_retention_until=now - timedelta(seconds=1),
        container_format="mp4",
        video_codec="h264",
        duration_seconds=1,
        fps=25,
        width=640,
        height=480,
        total_frames=25,
        processed_frames=5,
        sampling={"everyNFrames": 5},
    )


@pytest.mark.asyncio
async def test_cleanup_deletes_source_and_preserves_job():
    job = _job()
    minio = _Minio()
    service = VideoJobService(
        _Jobs([job]), _Tracks(), minio, session_factory=_Session
    )

    count = await service.cleanup_expired_sources(limit=10)

    assert count == 1
    assert minio.deleted == [job.source_object_key]
    assert job.source_deleted_at is not None
    assert job.status == "completed"
