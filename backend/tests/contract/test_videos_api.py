from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.presentation.dependencies import get_video_job_service, get_video_upload_service

JOB_ID = str(uuid4())
PROCESS_ID = str(uuid4())
NOW = datetime.now(UTC).isoformat()


def _job(status: str = "pending") -> dict:
    return {
        "job_id": JOB_ID,
        "process_id": PROCESS_ID,
        "status": status,
        "stage": "queued" if status == "pending" else status,
        "progress_percent": 0.0,
        "cancellation_requested": status in {"cancelling", "cancelled"},
        "error_code": None,
        "video": {
            "duration": 10.0,
            "fps": 25.0,
            "width": 640,
            "height": 480,
            "total_frames": 250,
            "processed_frames": 0,
            "sampling": {"mode": "every_n_frames", "everyNFrames": 5},
            "source_available": True,
        },
        "person_count": 0,
        "created_at": NOW,
        "started_at": None,
        "completed_at": None,
        "cancelled_at": None,
    }


class _UploadService:
    async def submit(self, video, sampling_mode, every_n_frames, frames_per_second, process_id):
        assert await video.read() == b"video"
        assert sampling_mode == "every_n_frames"
        assert every_n_frames == 5
        return {
            "job_id": JOB_ID,
            "process_id": process_id,
            "status": "pending",
            "status_url": f"/api/v1/videos/jobs/{JOB_ID}",
            "result_url": f"/api/v1/videos/jobs/{JOB_ID}/result",
        }


class _JobService:
    async def get(self, job_id):
        assert job_id == JOB_ID
        return _job()

    async def cancel(self, job_id):
        assert job_id == JOB_ID
        return _job("cancelled")


def _client() -> TestClient:
    app.dependency_overrides[get_video_upload_service] = lambda: _UploadService()
    app.dependency_overrides[get_video_job_service] = lambda: _JobService()
    return TestClient(app)


def test_submit_video_returns_pending_job_urls():
    response = _client().post(
        "/api/v1/videos/recognize",
        files={"video": ("clip.mp4", b"video", "video/mp4")},
        data={"samplingMode": "every_n_frames", "everyNFrames": "5"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["jobId"] == JOB_ID
    assert body["status"] == "pending"
    assert body["resultUrl"].endswith("/result")


def test_job_status_and_cancellation_contracts():
    api = _client()

    status = api.get(f"/api/v1/videos/jobs/{JOB_ID}")
    cancelled = api.delete(f"/api/v1/videos/jobs/{JOB_ID}")

    assert status.status_code == 200
    assert status.json()["video"]["sampling"]["everyNFrames"] == 5
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def teardown_module():
    app.dependency_overrides.clear()
