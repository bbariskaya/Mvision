from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.infrastructure.database.models import ProcessRecord, VideoJob, VideoTrack
from app.infrastructure.database.repositories.process_repository import ProcessRecordRepository
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

    def scalar_one(self):
        return self._value


class _JobListResult:
    def __init__(self, jobs):
        self.jobs = jobs

    def scalars(self):
        return self

    def all(self):
        return self.jobs


class _ClaimSession:
    def __init__(self, job: VideoJob, active_count: int = 0):
        self.job = job
        self.active_count = active_count
        self.flushed = False
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _ScalarResult(None)
        if len(self.statements) == 2:
            return _ScalarResult(self.active_count)
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


class _StatementSession:
    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(None)


class _JobListSession:
    def __init__(self, jobs):
        self.jobs = jobs
        self.flushed = False

    async def execute(self, statement):
        self.statement = statement
        return _JobListResult(self.jobs)

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


def test_video_max_concurrent_jobs_is_environment_configurable(monkeypatch):
    monkeypatch.setenv("VIDEO_MAX_CONCURRENT_JOBS", "7")

    assert Settings(_env_file=None).video_max_concurrent_jobs == 7


@pytest.mark.parametrize(
    "name",
    [
        "VIDEO_MAX_UPLOAD_BYTES",
        "VIDEO_MAX_DURATION_SECONDS",
        "VIDEO_RETENTION_SECONDS",
        "VIDEO_MAX_CONCURRENT_JOBS",
        "VIDEO_JOB_TIMEOUT_SECONDS",
        "VIDEO_PROBE_TIMEOUT_SECONDS",
        "VIDEO_JOB_LEASE_SECONDS",
        "VIDEO_JOB_MAX_ATTEMPTS",
        "VIDEO_PROGRESS_UPDATE_INTERVAL_SECONDS",
        "VIDEO_APPEARANCE_MAX_GAP_SECONDS",
        "VIDEO_WORKER_POLL_SECONDS",
    ],
)
def test_video_operational_values_must_be_positive(monkeypatch, name):
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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
async def test_process_completion_persists_task_details():
    session = _StatementSession()
    details = {
        "operation": "recognize",
        "face_count": 1,
        "faces": [{"face_id": "face-1", "status": "known"}],
    }

    await ProcessRecordRepository().complete(
        session,
        "019f8000-0000-7000-8000-000000000002",
        1,
        details=details,
    )

    assert session.statement.compile().params["details"] == details


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
        max_concurrent_jobs=3,
    )

    assert claimed is job
    assert job.status == "processing"
    assert job.stage == "starting"
    assert job.worker_id == "video-worker-0"
    assert job.lease_token == "lease-1"
    assert job.lease_expires_at == now + timedelta(seconds=30)
    assert job.attempt_count == 1
    assert session.flushed is True
    assert "pg_advisory_xact_lock" in str(session.statements[0])
    assert "count" in str(session.statements[1]).lower()
    claimed_sql = str(session.statements[2].compile(dialect=postgresql.dialect()))
    assert "SKIP LOCKED" in claimed_sql


@pytest.mark.asyncio
async def test_claim_next_refuses_admission_at_global_concurrency_limit():
    job = _job()
    session = _ClaimSession(job, active_count=3)

    claimed = await VideoJobRepository().claim_next(
        session,
        worker_id="video-worker-0",
        lease_token="lease-1",
        now=datetime.now(UTC),
        lease_seconds=30,
        max_concurrent_jobs=3,
    )

    assert claimed is None
    assert len(session.statements) == 2
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_settle_exhausted_moves_expired_jobs_to_terminal_states():
    now = datetime.now(UTC)
    failed = _job("processing")
    failed.attempt_count = failed.max_attempts
    failed.lease_expires_at = now - timedelta(seconds=1)
    cancelled = _job("cancelling")
    cancelled.job_id = "019f8000-0000-7000-8000-000000000003"
    cancelled.process_id = "019f8000-0000-7000-8000-000000000004"
    cancelled.attempt_count = cancelled.max_attempts
    cancelled.lease_expires_at = now - timedelta(seconds=1)
    session = _JobListSession([failed, cancelled])

    settled = await VideoJobRepository().settle_exhausted(session, now)

    assert settled == [
        (failed.process_id, "failed"),
        (cancelled.process_id, "cancelled"),
    ]
    assert failed.status == "failed"
    assert failed.error_code == "VIDEO_JOB_ATTEMPTS_EXHAUSTED"
    assert failed.completed_at == now
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at == now
    assert failed.lease_token is None
    assert cancelled.lease_token is None
    assert session.flushed is True


@pytest.mark.asyncio
async def test_lock_owned_requires_non_expired_owner_and_locks_row():
    session = _StatementSession()
    now = datetime.now(UTC)

    result = await VideoJobRepository().lock_owned(
        session,
        "019f8000-0000-7000-8000-000000000001",
        "video-worker-0",
        "lease-1",
        now,
    )

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert result is None
    assert "video_job.worker_id" in sql
    assert "video_job.lease_token" in sql
    assert "video_job.lease_expires_at" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_expired_owner_cannot_renew_or_update_progress():
    job = _job("processing")
    job.worker_id = "video-worker-0"
    job.lease_token = "lease-1"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    renew_session = _GetSession(job)
    progress_session = _GetSession(job)

    renewed = await VideoJobRepository().renew_lease(
        renew_session,
        job.job_id,
        "video-worker-0",
        "lease-1",
        datetime.now(UTC) + timedelta(seconds=30),
    )
    updated = await VideoJobRepository().update_progress(
        progress_session,
        job.job_id,
        "video-worker-0",
        "lease-1",
        stage="inference",
        progress_percent=50.0,
        processed_frames=10,
    )

    assert renewed is False
    assert updated is False
    assert renew_session.flushed is False
    assert progress_session.flushed is False


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
