from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.presentation.dependencies import get_live_connector_service

CONNECTOR_ID = "019f0000-0000-7000-8000-000000000010"


def _connector(enabled=True):
    return {
        "connector_id": CONNECTOR_ID,
        "type": "webhook",
        "name": "alerts",
        "enabled": enabled,
        "safe_config": {
            "authType": "bearer",
            "eventTypes": ["frame.result"],
            "timeoutSeconds": 5,
        },
        "created_at": "2026-07-23T12:00:00Z",
        "updated_at": "2026-07-23T12:00:00Z",
    }


class _ConnectorService:
    async def create(self, request):
        assert request.url.get_secret_value().startswith("https://")
        return _connector()

    async def list(self):
        return {"connectors": [_connector()]}

    async def get(self, connector_id):
        assert connector_id == CONNECTOR_ID
        return _connector()

    async def delete(self, connector_id):
        assert connector_id == CONNECTOR_ID
        return _connector(enabled=False)


def _client() -> TestClient:
    app.state.settings = Settings(_env_file=None, live_api_key="test-key")
    app.dependency_overrides[get_live_connector_service] = _ConnectorService
    return TestClient(app)


def _headers():
    return {"X-API-Key": "test-key"}


def test_connector_routes_require_internal_api_key() -> None:
    assert _client().get("/api/v1/live/connectors").status_code == 401


def test_live_connector_path_rejects_malformed_uuid_before_service() -> None:
    response = _client().get("/api/v1/live/connectors/not-a-uuid", headers=_headers())

    assert response.status_code == 422
    assert response.json()["code"] == "LIVE_CONNECTOR_SPEC_INVALID"


def test_webhook_connector_response_never_echoes_write_only_fields() -> None:
    secret_url = "https://hooks.example/events?token=hidden"
    secret_token = "write-only-token"
    response = _client().post(
        "/api/v1/live/connectors",
        headers=_headers(),
        json={
            "type": "webhook",
            "name": "alerts",
            "url": secret_url,
            "auth": {"type": "bearer", "token": secret_token},
            "eventTypes": ["frame.result"],
            "timeoutSeconds": 5,
        },
    )

    assert response.status_code == 201
    assert response.json()["connectorId"] == CONNECTOR_ID
    assert response.json()["safeConfig"]["authType"] == "bearer"
    assert secret_url not in response.text
    assert secret_token not in response.text


def test_invalid_connector_request_never_echoes_rejected_destination() -> None:
    secret_url = "ftp://alice:secret@hooks.example/events?token=hidden"

    response = _client().post(
        "/api/v1/live/connectors",
        headers=_headers(),
        json={
            "type": "webhook",
            "name": "alerts",
            "url": secret_url,
            "eventTypes": ["frame.result"],
        },
    )

    assert response.status_code == 422
    for forbidden in ("alice", "secret", "hooks.example", "token="):
        assert forbidden not in response.text


def test_list_get_and_delete_connector_contracts() -> None:
    client = _client()

    listed = client.get("/api/v1/live/connectors", headers=_headers())
    fetched = client.get(f"/api/v1/live/connectors/{CONNECTOR_ID}", headers=_headers())
    deleted = client.delete(f"/api/v1/live/connectors/{CONNECTOR_ID}", headers=_headers())

    assert listed.json()["connectors"][0]["connectorId"] == CONNECTOR_ID
    assert fetched.json()["enabled"] is True
    assert deleted.json()["enabled"] is False


def test_connector_response_schema_contains_no_write_only_fields() -> None:
    schemas = _client().get("/openapi.json").json()["components"]["schemas"]
    properties = schemas["LiveConnectorResponse"]["properties"]

    for forbidden in (
        "url",
        "auth",
        "token",
        "brokers",
        "username",
        "password",
        "caCertificate",
        "secretCiphertext",
    ):
        assert forbidden not in properties


def teardown_module() -> None:
    app.dependency_overrides.clear()
