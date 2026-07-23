from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.presentation.dependencies import get_live_session_service

SESSION_ID = "019f0000-0000-7000-8000-000000000001"


def _session(source_type="whipPush", publish_url=None, generation=1):
    return {
        "session_id": SESSION_ID,
        "generation": generation,
        "state": "WAITING_FOR_SOURCE",
        "camera_id": "gate-1",
        "location": None,
        "profile": {"id": "face-recognition-v1", "version": 1},
        "ingest": {"type": source_type, "publish_url": publish_url},
        "links": {
            "frames": f"/api/v1/live/sessions/{SESSION_ID}/frames",
            "appearances": f"/api/v1/live/sessions/{SESSION_ID}/appearances",
            "recordings": f"/api/v1/live/sessions/{SESSION_ID}/recordings",
        },
        "outputs": {
            "recording": {"state": "disabled", "urls": {}},
            "annotated_stream": {"state": "disabled", "urls": {}},
        },
    }


class _SessionService:
    def capabilities(self):
        return {
            "schema_versions": [1],
            "profiles": [{"id": "face-recognition-v1", "version": 1}],
            "source_types": ["rtspPull", "whepPull", "whipPush"],
            "processing_modes": ["detect", "detectTrack", "recognize"],
            "sampling_modes": ["everyNFrames", "framesPerSecond"],
            "connector_types": ["webhook", "kafka"],
            "max_concurrent_sessions": 1,
        }

    async def create(self, request):
        if request.source.type == "whipPush":
            return _session(publish_url="https://media.example/ingress/opaque/whip")
        assert request.source.url.get_secret_value().startswith(("rtsp://", "whep://"))
        return _session(request.source.type)

    async def list(self):
        return {"sessions": [_session(publish_url=None)]}

    async def get(self, session_id):
        assert session_id == SESSION_ID
        return _session(publish_url=None)

    async def reconfigure(self, session_id, request):
        assert session_id == SESSION_ID
        return _session(request.source.type, generation=2)

    async def stop(self, session_id):
        assert session_id == SESSION_ID
        result = _session(publish_url=None)
        result["state"] = "STOPPING"
        return result


def _client() -> TestClient:
    app.state.settings = Settings(_env_file=None, live_api_key="test-key")
    app.dependency_overrides[get_live_session_service] = _SessionService
    return TestClient(app)


def _headers():
    return {"X-API-Key": "test-key"}


def _request(source):
    return {
        "schemaVersion": 1,
        "cameraId": "gate-1",
        "source": source,
        "json": {"persistFrames": True},
    }


def test_live_routes_require_internal_api_key() -> None:
    client = _client()

    assert client.get("/api/v1/live/capabilities").status_code == 401
    assert client.get("/api/v1/live/sessions").status_code == 401
    assert (
        client.post("/api/v1/live/sessions", json=_request({"type": "whipPush"})).status_code == 401
    )


def test_live_session_path_rejects_malformed_uuid_before_service() -> None:
    response = _client().get("/api/v1/live/sessions/not-a-uuid", headers=_headers())

    assert response.status_code == 422
    assert response.json()["code"] == "LIVE_SESSION_SPEC_INVALID"


def test_create_whip_session_returns_waiting_publish_url() -> None:
    response = _client().post(
        "/api/v1/live/sessions",
        headers=_headers(),
        json=_request({"type": "whipPush"}),
    )

    assert response.status_code == 201
    assert response.json()["state"] == "WAITING_FOR_SOURCE"
    assert response.json()["ingest"]["publishUrl"].endswith("/whip")
    assert "internal" not in response.text.lower()


def test_pull_session_never_echoes_source_url() -> None:
    secret = "rtsp://alice:secret@customer/live?token=hidden"
    response = _client().post(
        "/api/v1/live/sessions",
        headers=_headers(),
        json=_request({"type": "rtspPull", "url": secret}),
    )

    assert response.status_code == 201
    for forbidden in ("alice", "secret", "customer", "token="):
        assert forbidden not in response.text


def test_invalid_pull_request_never_echoes_rejected_source_secret() -> None:
    secret = "http://alice:secret@customer/live?token=hidden"

    response = _client().post(
        "/api/v1/live/sessions",
        headers=_headers(),
        json=_request({"type": "rtspPull", "url": secret}),
    )

    assert response.status_code == 422
    for forbidden in ("alice", "secret", "customer", "token="):
        assert forbidden not in response.text


def test_list_get_reconfigure_stop_and_capabilities_contracts() -> None:
    client = _client()
    reconfigure = {
        "schemaVersion": 1,
        "source": {"type": "whipPush"},
        "json": {"persistFrames": True},
    }

    capabilities = client.get("/api/v1/live/capabilities", headers=_headers())
    listed = client.get("/api/v1/live/sessions", headers=_headers())
    fetched = client.get(f"/api/v1/live/sessions/{SESSION_ID}", headers=_headers())
    changed = client.post(
        f"/api/v1/live/sessions/{SESSION_ID}/reconfigure",
        headers=_headers(),
        json=reconfigure,
    )
    stopped = client.post(f"/api/v1/live/sessions/{SESSION_ID}/stop", headers=_headers())

    assert capabilities.json()["sourceTypes"] == [
        "rtspPull",
        "whepPull",
        "whipPush",
    ]
    assert listed.json()["sessions"][0]["sessionId"] == SESSION_ID
    assert fetched.json()["ingest"]["publishUrl"] is None
    assert changed.json()["generation"] == 2
    assert stopped.json()["state"] == "STOPPING"


def test_live_openapi_declares_api_key_security() -> None:
    document = _client().get("/openapi.json").json()

    operation = document["paths"]["/api/v1/live/sessions"]["post"]
    assert {"LiveApiKey": []} in operation["security"]
    assert document["components"]["securitySchemes"]["LiveApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }


def teardown_module() -> None:
    app.dependency_overrides.clear()
