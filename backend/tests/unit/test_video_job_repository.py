from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.infrastructure.database.models import ProcessRecord, VideoJob, VideoTrack
from app.infrastructure.database.repositories.video_job_repository import VideoJobRepository


def _constraints(model: type) -> str:
    return " ".join(
        str(item.sqltext) for item in model.__table__.constraints if hasattr(item, "sqltext")
    )


def _job(status: str = "pending") -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        job_id="019f8000-0000-7000-8000-000000000001",
        process_id="019f8000-0000-7000-8000-000000000002",
        status=status,
        stage="queued",
        progress_percent=0,
        attempt_count=0,
        max_attempts=3,
        available_at=now,
        source_bucket="videos",
        source_object_key="videos/019f8000-0000-7000-8000-000000000001/source",
        source_content_type="video/mp4",
        source_size=100,
        source_sha256="0" * 64,
        source_retention_until=now + timedelta(days=7),
        container_format="mp4",
        video_codec="h264",
        duration_seconds=1.0,
        fps=25.0,
        width=640,
        height=480,
        total_frames=25,
        processed_frames=0,
        sampling={"mode": "every_n_frames", "everyNFrames": 5},
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ClaimSession:
    def __init__(self, job: VideoJob):
        self.job = job
        self.flushed = False

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(self.job)

    async def flush(self):
        self.flushed = True


class _GetSession:
    def __init__(self, job: VideoJob):
        self.job = job
        self.flushed = False

    async def get(self, model, key):
        assert model is VideoJob
        assert key == self.job.job_id
        return self.job

    async def flush(self):
        self.flushed = True


def test_video_settings_have_bounded_defaults(monkeypatch):
    monkeypatch.setenv("VIDEO_MAX_DURATION_SECONDS", "60")
    monkeypatch.setenv("VIDEO_ALLOWED_CONTAINERS", "mp4, MOV")
    settings = Settings(_env_file=None)

    assert settings.video_max_duration_seconds == 60
    assert settings.video_default_frames_per_second > 0
    assert settings.video_job_lease_seconds > 0
    assert settings.video_allowed_container_set == {"mp4", "mov"}


def test_models_allow_video_process_and_job_states():
    process_constraints = _constraints(ProcessRecord)
    job_constraints = _constraints(VideoJob)

    assert "video_recognize" in process_constraints
    assert "cancelled" in process_constraints
    for state in ("pending", "processing", "cancelling", "cancelled", "completed", "failed"):
        assert state in job_constraints
    assert {column.name for column in VideoTrack.__table__.columns} >= {
        "job_id",
        "face_id",
        "appearances",
        "detections",
    }


@pytest.mark.asyncio
async def test_claim_next_assigns_lease_and_increments_attempt():
    job = _job()
    session = _ClaimSession(job)
    now = datetime.now(UTC)

    claimed = await VideoJobRepository().claim_next(
        session,
        worker_id="video-worker-0",
        lease_token="lease-1",
        now=now,
        lease_seconds=30,
    )

    assert claimed is job
    assert job.status == "processing"
    assert job.stage == "starting"
    assert job.worker_id == "video-worker-0"
    assert job.lease_token == "lease-1"
    assert job.lease_expires_at == now + timedelta(seconds=30)
    assert job.attempt_count == 1
    assert session.flushed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial", "expected"),
    [("pending", "cancelled"), ("processing", "cancelling")],
)
async def test_request_cancel_uses_state_appropriate_transition(initial, expected):
    job = _job(initial)
    session = _GetSession(job)

    cancelled = await VideoJobRepository().request_cancel(session, job.job_id)

    assert cancelled is job
    assert job.status == expected
    assert job.cancellation_requested is True
    assert session.flushed is True
