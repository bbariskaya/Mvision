from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.models import LiveCamera, LiveCameraRun
from app.services.exceptions import LiveCameraError
from app.services.live_camera_service import LiveCameraService

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
NOW = datetime.now(UTC)


class _Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _SessionFactory:
    def __init__(self):
        self.session = _Session()

    def __call__(self):
        return self.session


def _camera() -> LiveCamera:
    return LiveCamera(
        camera_id=CAMERA_ID,
        name="north-entrance",
        uri_ciphertext="ciphertext",
        uri_fingerprint="fingerprint",
        desired_state="stopped",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class _Cameras:
    def __init__(self):
        self.camera = _camera()
        self.created: tuple[str, str, str] | None = None

    async def create(self, session, *, name, uri_ciphertext, uri_fingerprint):
        self.created = (name, uri_ciphertext, uri_fingerprint)
        self.camera.name = name
        self.camera.uri_ciphertext = uri_ciphertext
        self.camera.uri_fingerprint = uri_fingerprint
        return self.camera

    async def get(self, session, camera_id):
        return self.camera if camera_id == CAMERA_ID and self.camera.is_active else None

    async def list_active(self, session):
        return [self.camera] if self.camera.is_active else []

    async def set_desired(self, session, camera_id, desired_state):
        camera = await self.get(session, camera_id)
        if camera is not None:
            camera.desired_state = desired_state
        return camera

    async def soft_delete(self, session, camera_id, deleted_at):
        camera = await self.get(session, camera_id)
        if camera is not None:
            camera.desired_state = "stopped"
            camera.is_active = False
            camera.deleted_at = deleted_at
        return camera


class _Runs:
    def __init__(self, run: LiveCameraRun | None = None):
        self.run = run

    async def latest_for_camera(self, session, camera_id):
        return self.run if camera_id == CAMERA_ID else None


class _Events:
    async def list_page(self, session, camera_id, *, limit):
        return []

    async def get(self, session, camera_id, event_id):
        return None


class _Cipher:
    def encrypt(self, uri: str) -> str:
        assert uri == "rtsp://alice:secret@10.0.0.12/live?token=hidden"
        return "ciphertext"

    def fingerprint(self, uri: str) -> str:
        assert uri == "rtsp://alice:secret@10.0.0.12/live?token=hidden"
        return "fingerprint"


def _service(cameras=None, runs=None, cipher=None):
    sessions = _SessionFactory()
    service = LiveCameraService(
        cameras or _Cameras(),
        runs or _Runs(),
        _Events(),
        cipher if cipher is not None else _Cipher(),
        output_host="localhost",
        output_port=8554,
        session_factory=sessions,
    )
    return service, sessions


@pytest.mark.asyncio
async def test_register_encrypts_uri_and_returns_only_sanitized_camera() -> None:
    cameras = _Cameras()
    service, sessions = _service(cameras=cameras)

    result = await service.register(
        "north-entrance",
        "rtsp://alice:secret@10.0.0.12/live?token=hidden",
    )

    assert cameras.created == ("north-entrance", "ciphertext", "fingerprint")
    assert "uri" not in result
    assert result["runtime_state"] == "STOPPED"
    assert sessions.session.commits == 1


@pytest.mark.asyncio
async def test_start_changes_only_durable_desired_state() -> None:
    cameras = _Cameras()
    service, sessions = _service(cameras=cameras)

    result = await service.start(CAMERA_ID)

    assert cameras.camera.desired_state == "running"
    assert result["desired_state"] == "running"
    assert result["runtime_state"] == "STOPPED"
    assert sessions.session.commits == 1


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    cameras = _Cameras()
    cameras.camera.desired_state = "stopped"
    service, sessions = _service(cameras=cameras)

    first = await service.stop(CAMERA_ID)
    second = await service.stop(CAMERA_ID)

    assert first["desired_state"] == "stopped"
    assert second["desired_state"] == "stopped"
    assert sessions.session.commits == 2


@pytest.mark.asyncio
async def test_delete_soft_deletes_camera() -> None:
    cameras = _Cameras()
    service, sessions = _service(cameras=cameras)

    result = await service.delete(CAMERA_ID)

    assert result == {"camera_id": CAMERA_ID, "deleted": True}
    assert cameras.camera.is_active is False
    assert cameras.camera.deleted_at is not None
    assert sessions.session.commits == 1


class _ConstraintDiagnostic:
    constraint_name = "uq_live_single_running"


class _ConstraintError(Exception):
    diag = _ConstraintDiagnostic()


class _ConflictingCameras(_Cameras):
    async def set_desired(self, session, camera_id, desired_state):
        raise IntegrityError("set running", {}, _ConstraintError())


@pytest.mark.asyncio
async def test_start_maps_single_running_constraint_to_stable_error() -> None:
    service, sessions = _service(cameras=_ConflictingCameras())

    with pytest.raises(LiveCameraError) as error:
        await service.start(CAMERA_ID)

    assert error.value.error_code == "LIVE_CAMERA_LIMIT_REACHED"
    assert error.value.status_code == 409
    assert sessions.session.rollbacks == 1


@pytest.mark.asyncio
async def test_missing_camera_returns_stable_not_found_error() -> None:
    cameras = _Cameras()
    cameras.camera.is_active = False
    service, _ = _service(cameras=cameras)

    with pytest.raises(LiveCameraError) as error:
        await service.get(CAMERA_ID)

    assert error.value.error_code == "CAMERA_NOT_FOUND"
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_latest_native_run_is_runtime_source_of_truth() -> None:
    run = LiveCameraRun(
        run_id=RUN_ID,
        camera_id=CAMERA_ID,
        generation=2,
        runtime_state="ACTIVE",
        started_at=NOW,
        first_frame_at=NOW,
        last_frame_at=NOW,
        reconnect_count=1,
        output_path=f"/live/{CAMERA_ID}",
        metrics={"frames": 10},
    )
    service, _ = _service(runs=_Runs(run))

    result = await service.get(CAMERA_ID)

    assert result["runtime_state"] == "ACTIVE"
    assert result["output_url"] == f"rtsp://localhost:8554/live/{CAMERA_ID}"
