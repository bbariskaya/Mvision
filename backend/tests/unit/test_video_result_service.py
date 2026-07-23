from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.infrastructure.database.models import FaceIdentity, VideoJob
from app.infrastructure.video.protocol import VideoDetection, VideoTrackOutput
from app.services.face_matcher import FaceMatch
from app.services.video_identity_voting_service import VideoIdentityDecision
from app.services.video_result_service import (
    VideoFinalizationLeaseLostError,
    VideoResultService,
)
from app.services.video_tracking_service import VideoTrackingService


def _embedding(index: int = 0) -> tuple[float, ...]:
    values = [0.0] * 512
    values[index] = 1.0
    return tuple(values)


def _raw_track(tracker_id: int = 1) -> VideoTrackOutput:
    return VideoTrackOutput(
        tracker_id=tracker_id,
        embedding=_embedding(),
        representative_jpeg=b"\xff\xd8jpeg\xff\xd9",
        detections=(VideoDetection(5, 0.2, 1, 2, 3, 4, 0.9),),
    )


def _job() -> VideoJob:
    now = datetime.now(UTC)
    return VideoJob(
        job_id="019f8000-0000-7000-8000-000000000001",
        process_id="019f8000-0000-7000-8000-000000000002",
        status="processing",
        stage="inference",
        progress_percent=50,
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
        processed_frames=5,
        sampling={"everyNFrames": 5},
        worker_id="video-worker-0",
        lease_token="lease-1",
        lease_expires_at=now + timedelta(minutes=1),
    )


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        self.committed = True


class _Matcher:
    def __init__(self, match):
        self.match_value = match

    async def resolve(self, track):
        return self.match_value


class _Samples:
    def __init__(self):
        self.calls = []

    async def persist(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(sample_id=kwargs["sample_id"])


class _Results:
    def __init__(self):
        self.rows = []

    async def create(self, session, **kwargs):
        self.rows.append(kwargs)
        return SimpleNamespace(result_id=kwargs["result_id"])


class _Tracks:
    async def replace_for_job(self, session, job_id, tracks):
        self.rows = tracks
        return tracks


class _Jobs:
    def __init__(self, owned=True):
        self.owned = owned
        self.completions = []

    async def lock_owned(self, session, job_id, worker_id, lease_token, now):
        return self.job if self.owned else None

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
        self.completions.append((person_count, processed_frames))
        return True


class _Processes:
    def __init__(self):
        self.completions = []

    async def complete(self, session, process_id, face_count, details=None):
        self.completions.append((process_id, face_count, details))


def _service(match, *, owned=True):
    samples = _Samples()
    results = _Results()
    tracks = _Tracks()
    jobs = _Jobs(owned)
    processes = _Processes()
    jobs.job = _job()
    service = VideoResultService(
        Settings(_env_file=None),
        VideoTrackingService(0.8, 1.5),
        _Matcher(match),
        samples,
        results,
        tracks,
        jobs,
        processes,
        session_factory=_Session,
    )
    return service, samples, results, tracks, jobs, processes


@pytest.mark.asyncio
async def test_finalize_persists_known_identity_snapshot(tmp_path: Path):
    identity = FaceIdentity(
        face_id="019f8000-0000-7000-8000-000000000010",
        lifecycle_status="known",
        name="Ada",
        metadata_={"team": "vision"},
        is_active=True,
        version=3,
    )
    service, samples, results, tracks, jobs, processes = _service(
        VideoIdentityDecision(FaceMatch(identity, "sample-1", 0.91), 0.91)
    )

    finalized = await service.finalize(
        jobs.job,
        [_raw_track()],
        tmp_path / "source.mp4",
        "video-worker-0",
        "lease-1",
        5,
    )

    assert finalized.person_count == 1
    assert finalized.faces == (
        {
            "face_id": identity.face_id,
            "status": "known",
        },
    )
    assert samples.calls == []
    assert results.rows[0]["status_snapshot"] == "known"
    assert tracks.rows[0].name_snapshot == "Ada"
    assert tracks.rows[0].metadata_snapshot == {"team": "vision"}
    assert jobs.completions == [(1, 5)]
    assert processes.completions[0][2] == {
        "operation": "video_recognize",
        "video": {
            "duration": 1,
            "fps": 25,
            "width": 640,
            "height": 480,
            "total_frames": 25,
            "processed_frames": 5,
        },
        "person_count": 1,
        "faces": [{"face_id": identity.face_id, "status": "known"}],
    }


@pytest.mark.asyncio
async def test_finalize_creates_new_anonymous_sample(tmp_path: Path):
    service, samples, results, tracks, jobs, _ = _service(
        VideoIdentityDecision(None, 0.59)
    )

    finalized = await service.finalize(
        jobs.job,
        [_raw_track()],
        tmp_path / "source.mp4",
        "video-worker-0",
        "lease-1",
        5,
    )

    assert finalized.person_count == 1
    assert len(samples.calls) == 1
    assert samples.calls[0]["manage_process"] is False
    assert results.rows[0]["status_snapshot"] == "new_anonymous"
    assert results.rows[0]["match_confidence"] == pytest.approx(0.59)
    assert tracks.rows[0].name_snapshot is None
    assert tracks.rows[0].metadata_snapshot == {}
    assert tracks.rows[0].match_confidence == pytest.approx(0.59)


@pytest.mark.asyncio
async def test_finalize_refuses_lost_lease_before_result_writes(tmp_path: Path):
    service, samples, results, tracks, jobs, processes = _service(
        VideoIdentityDecision(None, 0.59), owned=False
    )

    with pytest.raises(VideoFinalizationLeaseLostError):
        await service.finalize(
            jobs.job,
            [_raw_track()],
            tmp_path / "source.mp4",
            "video-worker-0",
            "lease-1",
            5,
        )

    assert samples.calls == []
    assert results.rows == []
    assert not hasattr(tracks, "rows")
    assert jobs.completions == []
    assert processes.completions == []


@pytest.mark.asyncio
async def test_finalize_uses_deterministic_result_and_track_ids(tmp_path: Path):
    identity = FaceIdentity(
        face_id="019f8000-0000-7000-8000-000000000010",
        lifecycle_status="known",
        name="Ada",
        metadata_={},
        is_active=True,
        version=1,
    )
    service, _, results, tracks, jobs, _ = _service(
        VideoIdentityDecision(FaceMatch(identity, "sample-1", 0.91), 0.91)
    )

    await service.finalize(
        jobs.job,
        [_raw_track()],
        tmp_path / "source.mp4",
        "video-worker-0",
        "lease-1",
        5,
    )
    first_ids = (results.rows[-1]["result_id"], tracks.rows[-1].track_id)
    await service.finalize(
        jobs.job,
        [_raw_track()],
        tmp_path / "source.mp4",
        "video-worker-0",
        "lease-1",
        5,
    )

    assert (results.rows[-1]["result_id"], tracks.rows[-1].track_id) == first_ids
