import datetime
import json
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.presentation.schemas.live_connectors import LiveConnectorCreateRequest
from app.services.live_connector_service import LiveConnectorService


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Connectors:
    def __init__(self):
        self.created = None

    async def create(self, session, **kwargs):
        self.created = kwargs
        now = datetime.datetime.now(datetime.UTC)
        return SimpleNamespace(
            connector_id="019f0000-0000-7000-8000-000000000010",
            enabled=True,
            created_at=now,
            updated_at=now,
            **kwargs,
        )


class _Cipher:
    def __init__(self):
        self.value = None

    def encrypt_secret(self, value):
        self.value = value
        return "ciphertext"


def test_webhook_connector_rejects_url_without_host() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(LiveConnectorCreateRequest).validate_python(
            {
                "type": "webhook",
                "name": "alerts",
                "url": "https://",
                "eventTypes": ["frame.result"],
            }
        )


@pytest.mark.asyncio
async def test_webhook_connector_encrypts_destination_and_returns_safe_config() -> None:
    connectors = _Connectors()
    cipher = _Cipher()
    service = LiveConnectorService(connectors, cipher, session_factory=_Session)
    secret_url = "https://hooks.example/events?token=hidden"
    request = TypeAdapter(LiveConnectorCreateRequest).validate_python(
        {
            "type": "webhook",
            "name": "alerts",
            "url": secret_url,
            "auth": {"type": "bearer", "token": "write-only-token"},
            "eventTypes": ["frame.result"],
            "timeoutSeconds": 5,
        }
    )

    result = await service.create(request)

    encrypted = json.loads(cipher.value)
    assert encrypted == {"authToken": "write-only-token", "url": secret_url}
    assert connectors.created["secret_ciphertext"] == "ciphertext"
    assert connectors.created["safe_config"] == {
        "authType": "bearer",
        "eventTypes": ["frame.result"],
        "timeoutSeconds": 5.0,
    }
    assert secret_url not in str(result)
    assert "write-only-token" not in str(result)


@pytest.mark.asyncio
async def test_kafka_connector_encrypts_brokers_and_sasl_credentials() -> None:
    connectors = _Connectors()
    cipher = _Cipher()
    service = LiveConnectorService(connectors, cipher, session_factory=_Session)
    request = TypeAdapter(LiveConnectorCreateRequest).validate_python(
        {
            "type": "kafka",
            "name": "frame-events",
            "brokers": ["kafka.internal:9093"],
            "topic": "mvision.frames",
            "security": {
                "protocol": "saslSsl",
                "saslMechanism": "scramSha256",
                "username": "producer-user",
                "password": "producer-password",
                "caCertificate": "private-ca",
            },
            "acknowledgements": "all",
            "eventTypes": ["frame.result"],
        }
    )

    result = await service.create(request)

    encrypted = json.loads(cipher.value)
    assert encrypted == {
        "brokers": ["kafka.internal:9093"],
        "caCertificate": "private-ca",
        "password": "producer-password",
        "username": "producer-user",
    }
    assert connectors.created["safe_config"] == {
        "acknowledgements": "all",
        "eventTypes": ["frame.result"],
        "saslMechanism": "scramSha256",
        "securityProtocol": "saslSsl",
        "timeoutSeconds": 10.0,
        "topic": "mvision.frames",
    }
    for forbidden in (
        "kafka.internal",
        "producer-user",
        "producer-password",
        "private-ca",
    ):
        assert forbidden not in str(result)
