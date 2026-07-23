from types import SimpleNamespace

import pytest

from app.config import Settings
from app.presentation.schemas.live_sessions import (
    LiveSessionCreateRequest,
    LiveSessionReconfigureRequest,
)
from app.services.exceptions import LiveSessionError
from app.services.live_session_compiler import LiveSessionCompiler
from app.services.live_session_service import LiveSessionService

SESSION_ID = "019f0000-0000-7000-8000-000000000001"
GENERATION_ID = "019f0000-0000-7000-8000-000000000002"


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


class _Sessions:
    def __init__(self):
        self.parent = None
        self.generations = []
        self.created_kwargs = []

    async def create_session(self, session, camera_external_id, location_snapshot):
        self.parent = SimpleNamespace(
            session_id=SESSION_ID,
            camera_external_id=camera_external_id,
            location_snapshot=location_snapshot,
            desired_state="running",
            current_generation=1,
        )
        return self.parent

    async def create_generation(self, session, **kwargs):
        if self.generations:
            self.generations[-1].desired_state = "stopped"
            self.generations[-1].runtime_state = "STOPPING"
            self.parent.current_generation = kwargs["generation"]
        generation = SimpleNamespace(
            generation_id=GENERATION_ID[:-1] + str(kwargs["generation"]),
            session_id=kwargs["session_id"],
            desired_state="running",
            runtime_state="ACCEPTED",
            media_state="provisioning",
            error_code=None,
            **{key: value for key, value in kwargs.items() if key != "session_id"},
        )
        self.generations.append(generation)
        self.created_kwargs.append(kwargs)
        return generation

    async def get(self, session, session_id):
        return self.parent if self.parent and session_id == SESSION_ID else None

    async def list(self, session):
        return [self.parent] if self.parent else []

    async def get_current_generation(self, session, session_id):
        if session_id != SESSION_ID or not self.generations:
            return None
        return self.generations[-1]

    async def set_desired_state(self, session, session_id, desired_state, now):
        if not self.parent or session_id != SESSION_ID:
            return None
        self.parent.desired_state = desired_state
        generation = self.generations[-1]
        generation.desired_state = desired_state
        if desired_state == "stopped" and generation.runtime_state not in {
            "STOPPED",
            "FAILED",
        }:
            generation.runtime_state = "STOPPING"
        return self.parent


class _Connectors:
    async def get(self, session, connector_id):
        return None


class _Cipher:
    def __init__(self):
        self.values = []

    def encrypt_secret(self, value):
        self.values.append(value)
        return "ciphertext"


class _Reconciler:
    def __init__(self, sessions):
        self.sessions = sessions
        self.calls = 0

    async def reconcile(self):
        self.calls += 1
        if self.sessions.generations:
            self.sessions.generations[-1].media_state = "waiting"


def _request(source, **overrides):
    value = {
        "schemaVersion": 1,
        "cameraId": "gate-1",
        "profile": "face-recognition-v1",
        "source": source,
        "processing": {"mode": "recognize"},
        "json": {"persistFrames": True},
    }
    value.update(overrides)
    return LiveSessionCreateRequest.model_validate(value)


def _service():
    sessions = _Sessions()
    cipher = _Cipher()
    reconciler = _Reconciler(sessions)
    session_factory = _SessionFactory()
    settings = Settings(
        _env_file=None,
        mediamtx_public_whip_origin="https://media.example",
    )
    service = LiveSessionService(
        settings,
        sessions,
        _Connectors(),
        LiveSessionCompiler(),
        cipher,
        reconciler,
        session_factory=session_factory,
    )
    return service, sessions, cipher, reconciler, session_factory


@pytest.mark.asyncio
async def test_create_pull_encrypts_source_and_persists_only_safe_snapshots() -> None:
    service, sessions, cipher, reconciler, session_factory = _service()
    secret = "rtsp://alice:secret@camera/live?token=hidden"

    result = await service.create(_request({"type": "rtspPull", "url": secret}))

    created = sessions.created_kwargs[0]
    assert cipher.values == [secret]
    assert created["source_ciphertext"] == "ciphertext"
    assert created["requested_spec"]["source"] == {"type": "rtspPull"}
    assert secret not in str(created["requested_spec"])
    assert secret not in str(created["resolved_spec"])
    assert secret not in str(result)
    assert result["ingest"] == {"type": "rtspPull", "publish_url": None}
    assert result["state"] == "WAITING_FOR_SOURCE"
    assert reconciler.calls == 1
    assert session_factory.session.commits == 1


@pytest.mark.asyncio
async def test_create_whip_returns_one_generation_scoped_publish_url() -> None:
    service, sessions, cipher, _, _ = _service()

    result = await service.create(_request({"type": "whipPush"}))

    assert cipher.values == []
    assert sessions.created_kwargs[0]["ingress_path"].startswith("ingress/")
    assert result["ingest"]["publish_url"].startswith("https://media.example/ingress/")
    assert result["ingest"]["publish_url"].endswith("/whip")


@pytest.mark.asyncio
async def test_reconfigure_creates_next_generation_and_stop_is_idempotent() -> None:
    service, sessions, _, reconciler, _ = _service()
    await service.create(_request({"type": "whipPush"}))
    request = LiveSessionReconfigureRequest.model_validate(
        {
            "schemaVersion": 1,
            "source": {"type": "whipPush"},
            "json": {"persistFrames": True},
        }
    )

    reconfigured = await service.reconfigure(SESSION_ID, request)
    first_stop = await service.stop(SESSION_ID)
    second_stop = await service.stop(SESSION_ID)

    assert reconfigured["generation"] == 2
    assert sessions.generations[0].desired_state == "stopped"
    assert sessions.generations[1].desired_state == "stopped"
    assert first_stop["state"] == "STOPPING"
    assert second_stop["state"] == "STOPPING"
    assert reconciler.calls == 4


@pytest.mark.asyncio
async def test_get_missing_session_has_stable_error() -> None:
    service, _, _, _, _ = _service()

    with pytest.raises(LiveSessionError) as raised:
        await service.get("019f0000-0000-7000-8000-000000000099")

    assert raised.value.error_code == "LIVE_SESSION_NOT_FOUND"
    assert raised.value.status_code == 404


def test_capabilities_are_bounded_to_current_delivery() -> None:
    service, _, _, _, _ = _service()

    result = service.capabilities()

    assert result["schema_versions"] == [1]
    assert result["source_types"] == ["rtspPull", "whepPull", "whipPush"]
    assert result["max_concurrent_sessions"] == 1
