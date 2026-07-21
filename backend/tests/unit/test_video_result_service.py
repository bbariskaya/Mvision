from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.infrastructure.database.models import FaceIdentity, VideoJob
from app.infrastructure.video.protocol import VideoDetection, VideoTrackOutput
from app.services.face_matcher import FaceMatch
from app.services.video_result_service import VideoResultService
from app.services.video_identity_voting_service import VideoIdentityDecision
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


def _service(match):
    samples = _Samples()
    results = _Results()
    tracks = _Tracks()
    service = VideoResultService(
        Settings(_env_file=None),
        VideoTrackingService(0.8, 1.5),
        _Matcher(match),
        samples,
        results,
        tracks,
        session_factory=_Session,
    )
    return service, samples, results, tracks


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
    service, samples, results, tracks = _service(
        VideoIdentityDecision(FaceMatch(identity, "sample-1", 0.91), 0.91)
    )

    count = await service.finalize(_job(), [_raw_track()], tmp_path / "source.mp4")

    assert count == 1
    assert samples.calls == []
    assert results.rows[0]["status_snapshot"] == "known"
    assert tracks.rows[0].name_snapshot == "Ada"
    assert tracks.rows[0].metadata_snapshot == {"team": "vision"}


@pytest.mark.asyncio
async def test_finalize_creates_new_anonymous_sample(tmp_path: Path):
    service, samples, results, tracks = _service(VideoIdentityDecision(None, 0.59))

    count = await service.finalize(_job(), [_raw_track()], tmp_path / "source.mp4")

    assert count == 1
    assert len(samples.calls) == 1
    assert samples.calls[0]["manage_process"] is False
    assert results.rows[0]["status_snapshot"] == "new_anonymous"
    assert results.rows[0]["match_confidence"] == pytest.approx(0.59)
    assert tracks.rows[0].name_snapshot is None
    assert tracks.rows[0].metadata_snapshot == {}
    assert tracks.rows[0].match_confidence == pytest.approx(0.59)
