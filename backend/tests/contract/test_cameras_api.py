from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.presentation.dependencies import get_live_camera_service
from app.services.exceptions import LiveCameraError

CAMERA_ID = str(uuid4())
EVENT_ID = str(uuid4())
RUN_ID = str(uuid4())
NOW = datetime.now(UTC)


def _camera(desired_state: str = "stopped", runtime_state: str = "STOPPED") -> dict:
    return {
        "camera_id": CAMERA_ID,
        "name": "north-entrance",
        "desired_state": desired_state,
        "runtime_state": runtime_state,
        "output_url": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


class _CameraService:
    async def register(self, name: str, rtsp_uri: str) -> dict:
        assert name == "north-entrance"
        assert rtsp_uri == "rtsp://alice:secret@10.0.0.12/live?token=hidden"
        return _camera()

    async def list(self) -> list[dict]:
        return [_camera()]

    async def get(self, camera_id: str) -> dict:
        assert camera_id == CAMERA_ID
        return _camera()

    async def start(self, camera_id: str) -> dict:
        assert camera_id == CAMERA_ID
        return _camera("running", "STOPPED")

    async def stop(self, camera_id: str) -> dict:
        assert camera_id == CAMERA_ID
        return _camera()

    async def delete(self, camera_id: str) -> dict:
        assert camera_id == CAMERA_ID
        return {"camera_id": CAMERA_ID, "deleted": True}

    async def events(self, camera_id: str, limit: int) -> dict:
        assert camera_id == CAMERA_ID
        assert limit == 50
        return {"camera_id": CAMERA_ID, "events": [], "next_cursor": None}

    async def health(self, camera_id: str) -> dict:
        assert camera_id == CAMERA_ID
        return {
            "camera_id": CAMERA_ID,
            "run_id": RUN_ID,
            "generation": 1,
            "desired_state": "running",
            "runtime_state": "ACTIVE",
            "first_frame_at": NOW,
            "last_frame_at": NOW,
            "reconnect_count": 0,
            "metrics": {"frames": 10},
            "output_url": "rtsp://localhost:8554/live/camera",
            "error_code": None,
        }

    async def snapshot(self, camera_id: str, event_id: str) -> dict:
        assert camera_id == CAMERA_ID
        assert event_id == EVENT_ID
        return {"data": b"jpeg", "media_type": "image/jpeg"}


class _ConflictingCameraService(_CameraService):
    async def start(self, camera_id: str) -> dict:
        raise LiveCameraError(
            "Another camera is already running",
            "LIVE_CAMERA_LIMIT_REACHED",
            409,
        )


def _client(service=None) -> TestClient:
    app.dependency_overrides[get_live_camera_service] = lambda: service or _CameraService()
    return TestClient(app)


def test_register_camera_never_echoes_uri_components() -> None:
    response = _client().post(
        "/api/v1/cameras",
        json={
            "name": "north-entrance",
            "rtspUri": "rtsp://alice:secret@10.0.0.12/live?token=hidden",
        },
    )

    assert response.status_code == 201
    assert response.json()["cameraId"] == CAMERA_ID
    for forbidden in ("rtsp://", "alice", "secret", "10.0.0.12", "token="):
        assert forbidden not in response.text


def test_list_get_start_stop_and_delete_camera_contracts() -> None:
    client = _client()

    listed = client.get("/api/v1/cameras")
    fetched = client.get(f"/api/v1/cameras/{CAMERA_ID}")
    started = client.post(f"/api/v1/cameras/{CAMERA_ID}/start")
    stopped = client.post(f"/api/v1/cameras/{CAMERA_ID}/stop")
    deleted = client.delete(f"/api/v1/cameras/{CAMERA_ID}")

    assert listed.json()["cameras"][0]["cameraId"] == CAMERA_ID
    assert fetched.json()["runtimeState"] == "STOPPED"
    assert started.json()["desiredState"] == "running"
    assert started.json()["runtimeState"] == "STOPPED"
    assert stopped.json()["desiredState"] == "stopped"
    assert deleted.json() == {"cameraId": CAMERA_ID, "deleted": True}


def test_events_health_and_snapshot_contracts() -> None:
    client = _client()

    events = client.get(f"/api/v1/cameras/{CAMERA_ID}/events")
    health = client.get(f"/api/v1/cameras/{CAMERA_ID}/health")
    snapshot = client.get(f"/api/v1/cameras/{CAMERA_ID}/events/{EVENT_ID}/snapshot")

    assert events.status_code == 200
    assert events.json()["events"] == []
    assert health.json()["runtimeState"] == "ACTIVE"
    assert health.json()["metrics"] == {"frames": 10}
    assert snapshot.content == b"jpeg"
    assert snapshot.headers["content-type"] == "image/jpeg"


def test_second_camera_start_returns_exact_limit_error() -> None:
    response = _client(_ConflictingCameraService()).post(
        f"/api/v1/cameras/{CAMERA_ID}/start"
    )

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "LIVE_CAMERA_LIMIT_REACHED"}}


def test_camera_response_schema_contains_no_secret_field() -> None:
    schema = _client().get("/openapi.json").json()["components"]["schemas"]
    properties = schema["CameraResponse"]["properties"]

    assert "rtspUri" not in properties
    assert "uri" not in properties
    assert "uriCiphertext" not in properties
    assert "uriFingerprint" not in properties


def teardown_module() -> None:
    app.dependency_overrides.clear()
