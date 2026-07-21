from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.infrastructure.database.models import VideoJob
from app.infrastructure.video.native_runner import NativeVideoCancelledError
from app.infrastructure.video.protocol import VideoCompleted, VideoProgress
from app.services.video_processor import VideoJobProcessor


def _job() -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        job_id="019f8000-0000-7000-8000-000000000001",
        process_id="019f8000-0000-7000-8000-000000000002",
        status="processing",
        stage="starting",
        progress_percent=0,
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        source_bucket="videos",
        source_object_key="videos/019f8000-0000-7000-8000-000000000001/source",
        source_content_type="video/mp4",
        source_size=5,
        source_sha256="0" * 64,
        source_retention_until=now + timedelta(days=7),
        container_format="mp4",
        video_codec="h264",
        duration_seconds=1,
        fps=25,
        width=640,
        height=480,
        total_frames=25,
        processed_frames=0,
        sampling={"everyNFrames": 5},
    )


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        self.committed = True


class _Jobs:
    def __init__(self, job):
        self.job = job
        self.completed = None
        self.cancelled = False

    async def claim_next(self, session, **kwargs):
        return self.job

    async def update_progress(self, session, job_id, worker_id, lease_token, **kwargs):
        self.progress = kwargs
        return True

    async def get_by_id(self, session, job_id):
        return self.job

    async def complete(
        self,
        session,
        job_id,
        worker_id,
        lease_token,
        person_count,
        *,
        processed_frames,
    ):
        self.completed = (person_count, processed_frames)
        return True

    async def mark_cancelled(self, session, job_id, worker_id, lease_token):
        self.cancelled = True
        return True

    async def fail(self, *args, **kwargs):
        self.failed = kwargs.get("error_code") or args[-1]
        return True

    async def release_for_retry(self, *args, **kwargs):
        self.retried = True
        return True


class _Processes:
    async def complete(self, session, process_id, face_count):
        self.completed = face_count

    async def cancel(self, session, process_id):
        self.cancelled = process_id

    async def fail(self, session, process_id, error_code):
        self.failed = error_code


class _Minio:
    async def download_video(self, object_key, destination: Path):
        destination.write_bytes(b"video")


class _Runner:
    async def run(self, job, path, on_event, cancellation_requested):
        await on_event(VideoProgress(5, 1, 25, 20.0))
        return VideoCompleted(25, 5, 0)


class _CancelledRunner:
    async def run(self, job, path, on_event, cancellation_requested):
        raise NativeVideoCancelledError()


@pytest.mark.asyncio
async def test_processor_completes_claimed_job(tmp_path: Path):
    job = _job()
    jobs = _Jobs(job)
    processes = _Processes()
    finalized = []

    async def finalize(selected_job, tracks, source_path):
        finalized.append((selected_job.job_id, tracks, source_path.read_bytes()))
        return 0

    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        _Runner(),
        finalize,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    processed = await processor.process_one_job("worker-0")

    assert processed is True
    assert jobs.progress["processed_frames"] == 1
    assert jobs.completed == (0, 5)
    assert processes.completed == 0
    assert finalized == [(job.job_id, [], b"video")]


@pytest.mark.asyncio
async def test_processor_marks_cancelled_native_job(tmp_path: Path):
    job = _job()
    jobs = _Jobs(job)
    processes = _Processes()
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        _CancelledRunner(),
        lambda job, tracks, source_path: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is True
    assert jobs.cancelled is True
    assert processes.cancelled == job.process_id
