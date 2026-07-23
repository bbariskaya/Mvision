from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.exceptions import ValidationError
from app.services.video_job_service import VideoJobService
from app.services.video_upload_service import resolve_sampling


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_resolve_sampling_uses_configured_default():
    value = resolve_sampling(_settings(), source_fps=25.0)

    assert value["mode"] == "frames_per_second"
    assert value["requestedFramesPerSecond"] == 2.0
    assert value["everyNFrames"] == 12
    assert value["effectiveFramesPerSecond"] == pytest.approx(25 / 12)


def test_resolve_sampling_validates_mode_specific_fields():
    with pytest.raises(ValidationError) as exc:
        resolve_sampling(
            _settings(),
            source_fps=25.0,
            mode="every_n_frames",
            every_n_frames=0,
        )

    assert exc.value.error_code == "INVALID_SAMPLING"


def test_resolve_sampling_rejects_target_above_source_fps():
    with pytest.raises(ValidationError):
        resolve_sampling(
            _settings(),
            source_fps=25.0,
            mode="frames_per_second",
            frames_per_second=30.0,
        )


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass


class _Jobs:
    def __init__(self, job):
        self.job = job

    async def get_by_id(self, session, job_id):
        return self.job

    async def request_cancel(self, session, job_id):
        self.job.cancellation_requested = True
        if self.job.status == "pending":
            self.job.status = "cancelled"
            self.job.stage = "cancelled"
        elif self.job.status == "processing":
            self.job.status = "cancelling"
            self.job.stage = "cancelling"
        return self.job


class _Tracks:
    def __init__(self):
        self.deleted = []

    async def delete_for_job(self, session, job_id):
        self.deleted.append(job_id)


class _Processes:
    def __init__(self):
        self.cancelled = []

    async def cancel(self, session, process_id):
        self.cancelled.append(process_id)


class _Minio:
    pass


def _video_job(status):
    return SimpleNamespace(
        job_id="job-1",
        process_id="process-1",
        status=status,
        stage=status,
        progress_percent=0.0,
        cancellation_requested=status in {"cancelling", "cancelled"},
        error_code=None,
        duration_seconds=1.0,
        fps=25.0,
        width=640,
        height=480,
        total_frames=25,
        processed_frames=0,
        sampling={},
        source_deleted_at=None,
        person_count=0,
        created_at=None,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
    )


@pytest.mark.asyncio
async def test_pending_cancellation_cancels_process_and_removes_partial_tracks():
    job = _video_job("pending")
    tracks = _Tracks()
    processes = _Processes()
    service = VideoJobService(
        _Jobs(job), tracks, processes, _Minio(), session_factory=_Session
    )

    result = await service.cancel(job.job_id)

    assert result["status"] == "cancelled"
    assert tracks.deleted == [job.job_id]
    assert processes.cancelled == [job.process_id]


@pytest.mark.asyncio
async def test_processing_and_repeated_terminal_cancellation_are_consistent():
    processing = _video_job("processing")
    processing_tracks = _Tracks()
    processing_processes = _Processes()
    processing_service = VideoJobService(
        _Jobs(processing),
        processing_tracks,
        processing_processes,
        _Minio(),
        session_factory=_Session,
    )

    result = await processing_service.cancel(processing.job_id)

    assert result["status"] == "cancelling"
    assert processing_tracks.deleted == []
    assert processing_processes.cancelled == []

    cancelled = _video_job("cancelled")
    terminal_tracks = _Tracks()
    terminal_processes = _Processes()
    terminal_service = VideoJobService(
        _Jobs(cancelled),
        terminal_tracks,
        terminal_processes,
        _Minio(),
        session_factory=_Session,
    )

    repeated = await terminal_service.cancel(cancelled.job_id)

    assert repeated["status"] == "cancelled"
    assert terminal_tracks.deleted == []
    assert terminal_processes.cancelled == []
