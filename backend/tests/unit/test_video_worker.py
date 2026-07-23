import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.infrastructure.database.models import VideoJob
from app.infrastructure.video.native_runner import (
    NativeVideoCancelledError,
    NativeVideoFailedError,
    NativeVideoTimeoutError,
)
from app.infrastructure.video.protocol import VideoCompleted, VideoProgress
from app.services.video_processor import VideoJobProcessor
from app.services.video_result_service import VideoFinalizationResult


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
    def __init__(
        self,
        job,
        *,
        progress_allowed=True,
        renewal_allowed=True,
        cancellation_allowed=True,
        settled=(),
    ):
        self.job = job
        self.progress_allowed = progress_allowed
        self.renewal_allowed = renewal_allowed
        self.cancellation_allowed = cancellation_allowed
        self.settled = settled
        self.completed = None
        self.cancelled = False
        self.failed = None
        self.retried = False

    async def settle_exhausted(self, session, now):
        return self.settled

    async def claim_next(self, session, **kwargs):
        self.claim_kwargs = kwargs
        return self.job

    async def update_progress(self, session, job_id, worker_id, lease_token, **kwargs):
        self.progress = kwargs
        return self.progress_allowed

    async def renew_lease(self, session, job_id, worker_id, lease_token, expires_at):
        return self.renewal_allowed

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
        self.cancelled = self.cancellation_allowed
        return self.cancellation_allowed

    async def fail(self, *args, **kwargs):
        self.failed = kwargs.get("error_code") or args[-1]
        return True

    async def release_for_retry(self, *args, **kwargs):
        self.retried = True
        return True


class _Processes:
    def __init__(self):
        self.completed = None
        self.cancelled = None
        self.failed = None

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


class _FailedRunner:
    def __init__(self, error):
        self.error = error

    async def run(self, job, path, on_event, cancellation_requested):
        raise self.error


class _ProgressLeaseLossRunner:
    def __init__(self):
        self.cancelled = False

    async def run(self, job, path, on_event, cancellation_requested):
        try:
            await on_event(VideoProgress(5, 1, 25, 20.0))
        except Exception:
            self.cancelled = True
            raise


class _RenewalLeaseLossRunner:
    def __init__(self, sleep):
        self.sleep = sleep
        self.cancelled = False

    async def run(self, job, path, on_event, cancellation_requested):
        for _ in range(10):
            await self.sleep(0)
            if await cancellation_requested():
                self.cancelled = True
                raise NativeVideoCancelledError()
        raise AssertionError("lease loss was not propagated to native cancellation")


@pytest.mark.asyncio
async def test_processor_completes_claimed_job(tmp_path: Path):
    job = _job()
    jobs = _Jobs(job)
    processes = _Processes()
    finalized = []

    async def finalize(
        selected_job, tracks, source_path, worker_id, lease_token, processed_frames
    ):
        finalized.append(
            (
                selected_job.job_id,
                tracks,
                source_path.read_bytes(),
                worker_id,
                lease_token,
                processed_frames,
            )
        )
        return VideoFinalizationResult(0, ())

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
    assert jobs.claim_kwargs["max_concurrent_jobs"] == 3
    assert jobs.completed is None
    assert processes.completed is None
    assert finalized[0][0:4] == (job.job_id, [], b"video", "worker-0")
    assert finalized[0][4]
    assert finalized[0][5] == 5


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


@pytest.mark.asyncio
async def test_stale_cancel_transition_does_not_cancel_process(tmp_path: Path):
    job = _job()
    jobs = _Jobs(job, cancellation_allowed=False)
    processes = _Processes()
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        _CancelledRunner(),
        lambda *args: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is True
    assert jobs.cancelled is False
    assert processes.cancelled is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NativeVideoTimeoutError("timed out"), "VIDEO_PROCESSING_TIMEOUT"),
        (
            NativeVideoFailedError("VIDEO_DECODE_FAILED", "decode failed"),
            "VIDEO_DECODE_FAILED",
        ),
    ],
)
async def test_terminal_native_failure_preserves_error_code(tmp_path: Path, error, code):
    job = _job()
    job.attempt_count = job.max_attempts
    jobs = _Jobs(job)
    processes = _Processes()
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        _FailedRunner(error),
        lambda *args: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is True
    assert jobs.failed == code
    assert processes.failed == code


@pytest.mark.asyncio
async def test_processor_settles_exhausted_parent_processes_before_claim(tmp_path: Path):
    failed_process = "019f8000-0000-7000-8000-000000000010"
    cancelled_process = "019f8000-0000-7000-8000-000000000011"
    jobs = _Jobs(
        None,
        settled=((failed_process, "failed"), (cancelled_process, "cancelled")),
    )
    processes = _Processes()
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        _Runner(),
        lambda job, tracks, source_path: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is False
    assert processes.failed == "VIDEO_JOB_ATTEMPTS_EXHAUSTED"
    assert processes.cancelled == cancelled_process


@pytest.mark.asyncio
async def test_stale_progress_cancels_native_without_durable_mutation(tmp_path: Path):
    job = _job()
    jobs = _Jobs(job, progress_allowed=False)
    processes = _Processes()
    runner = _ProgressLeaseLossRunner()
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        runner,
        lambda job, tracks, source_path: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is True
    assert runner.cancelled is True
    assert jobs.completed is None
    assert jobs.cancelled is False
    assert jobs.failed is None
    assert jobs.retried is False
    assert processes.completed is None
    assert processes.cancelled is None
    assert processes.failed is None


@pytest.mark.asyncio
async def test_failed_renewal_cancels_native_without_durable_mutation(
    tmp_path: Path, monkeypatch
):
    original_sleep = asyncio.sleep

    async def immediate_sleep(delay):
        await original_sleep(0)

    monkeypatch.setattr("app.services.video_processor.asyncio.sleep", immediate_sleep)
    job = _job()
    jobs = _Jobs(job, renewal_allowed=False)
    processes = _Processes()
    runner = _RenewalLeaseLossRunner(original_sleep)
    processor = VideoJobProcessor(
        Settings(_env_file=None),
        _Minio(),
        jobs,
        processes,
        runner,
        lambda job, tracks, source_path: None,
        session_factory=_Session,
        temp_root=tmp_path,
    )

    assert await processor.process_one_job("worker-0") is True
    assert runner.cancelled is True
    assert jobs.completed is None
    assert jobs.cancelled is False
    assert jobs.failed is None
    assert jobs.retried is False
    assert processes.completed is None
    assert processes.cancelled is None
    assert processes.failed is None
