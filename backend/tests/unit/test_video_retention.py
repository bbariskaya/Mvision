from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.infrastructure.database.models import VideoJob
from app.services.exceptions import VideoError
from app.services.video_job_service import VideoJobService
from app.worker.video_worker_main import run_iteration


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

    async def get_by_id(self, session, job_id):
        return next((job for job in self.jobs if job.job_id == job_id), None)


class _Tracks:
    pass


class _Processes:
    pass


class _Minio:
    def __init__(self, failing=()):
        self.deleted = []
        self.failing = set(failing)

    async def delete_video(self, object_key):
        if object_key in self.failing:
            raise RuntimeError("delete failed")
        self.deleted.append(object_key)

    async def read_video_range(self, object_key, offset, length):
        return b"video"


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
        _Jobs([job]), _Tracks(), _Processes(), minio, session_factory=_Session
    )

    count = await service.cleanup_expired_sources(limit=10)

    assert count == 1
    assert minio.deleted == [job.source_object_key]
    assert job.source_deleted_at is not None
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_source_is_expired_at_retention_timestamp_before_cleanup():
    job = _job()
    service = VideoJobService(
        _Jobs([job]), _Tracks(), _Processes(), _Minio(), session_factory=_Session
    )

    with pytest.raises(VideoError) as exc:
        await service.source(job.job_id, None)

    assert exc.value.error_code == "VIDEO_EXPIRED"
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_cleanup_isolates_each_object_deletion_failure():
    failed = _job()
    successful = _job()
    successful.job_id = "019f8000-0000-7000-8000-000000000003"
    successful.source_object_key = (
        "videos/019f8000-0000-7000-8000-000000000003/source"
    )
    minio = _Minio({failed.source_object_key})
    service = VideoJobService(
        _Jobs([failed, successful]),
        _Tracks(),
        _Processes(),
        minio,
        session_factory=_Session,
    )

    count = await service.cleanup_expired_sources(limit=10)

    assert count == 1
    assert failed.source_deleted_at is None
    assert successful.source_deleted_at is not None
    assert minio.deleted == [successful.source_object_key]


@pytest.mark.asyncio
async def test_worker_runs_cleanup_even_after_processing_a_job():
    calls = []

    class _Processor:
        async def process_one_job(self, worker_id):
            calls.append(("process", worker_id))
            return True

    class _JobService:
        async def cleanup_expired_sources(self):
            calls.append(("cleanup", None))

    container = SimpleNamespace(
        video_processor=_Processor(),
        video_jobs=_JobService(),
        settings=SimpleNamespace(video_worker_poll_seconds=0.01),
    )

    await run_iteration(container, "worker-0")

    assert calls == [("process", "worker-0"), ("cleanup", None)]
