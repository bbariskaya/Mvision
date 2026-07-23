import json
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.repositories.live_connector_repository import (
    LiveConnectorRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.presentation.schemas.live_connectors import (
    KafkaConnectorCreateRequest,
    LiveConnectorCreateRequest,
    WebhookBearerAuth,
    WebhookConnectorCreateRequest,
)
from app.services.exceptions import LiveConnectorError


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class SecretCipher(Protocol):
    def encrypt_secret(self, value: str) -> str: ...


class LiveConnectorService:
    def __init__(
        self,
        connectors: LiveConnectorRepository,
        cipher: SecretCipher | None,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
    ):
        self._connectors = connectors
        self._cipher = cipher
        self._session_factory = session_factory

    async def create(self, request: LiveConnectorCreateRequest) -> dict[str, Any]:
        if self._cipher is None:
            raise LiveConnectorError(
                "Live connector encryption is unavailable",
                "LIVE_SECRET_CONFIGURATION_REQUIRED",
                503,
            )
        name = request.name.strip()
        if not name:
            raise LiveConnectorError(
                "Connector name must not be empty",
                "LIVE_CONNECTOR_SPEC_INVALID",
                422,
            )
        safe_config, secrets = self._split_config(request)
        try:
            ciphertext = self._cipher.encrypt_secret(
                json.dumps(secrets, sort_keys=True, separators=(",", ":"))
            )
        except ValueError as exc:
            raise LiveConnectorError(
                "Connector secret configuration is invalid",
                "LIVE_CONNECTOR_CREDENTIAL_INVALID",
                422,
            ) from exc
        async with self._session_factory() as session:
            try:
                connector = await self._connectors.create(
                    session,
                    connector_type=request.type,
                    name=name,
                    safe_config=safe_config,
                    secret_ciphertext=ciphertext,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise LiveConnectorError(
                    "Live connector name already exists",
                    "LIVE_CONNECTOR_CONFLICT",
                    409,
                ) from exc
            return self._snapshot(connector)

    async def list(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            connectors = await self._connectors.list(session)
            return {"connectors": [self._snapshot(item) for item in connectors]}

    async def get(self, connector_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            connector = await self._connectors.get(session, connector_id)
            if connector is None:
                raise self._not_found()
            return self._snapshot(connector)

    async def delete(self, connector_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            connector = await self._connectors.disable(session, connector_id)
            if connector is None:
                raise self._not_found()
            await session.commit()
            return self._snapshot(connector)

    @staticmethod
    def _split_config(
        request: LiveConnectorCreateRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(request, WebhookConnectorCreateRequest):
            token = (
                request.auth.token.get_secret_value()
                if isinstance(request.auth, WebhookBearerAuth)
                else None
            )
            return (
                {
                    "authType": request.auth.type,
                    "eventTypes": list(request.event_types),
                    "timeoutSeconds": request.timeout_seconds,
                },
                {
                    "authToken": token,
                    "url": request.url.get_secret_value(),
                },
            )

        assert isinstance(request, KafkaConnectorCreateRequest)
        security = request.security
        if security.protocol in {"saslPlaintext", "saslSsl"} and (
            security.sasl_mechanism is None
            or security.username is None
            or security.password is None
        ):
            raise LiveConnectorError(
                "Kafka SASL configuration is incomplete",
                "LIVE_CONNECTOR_SPEC_INVALID",
                422,
            )
        return (
            {
                "acknowledgements": request.acknowledgements,
                "eventTypes": list(request.event_types),
                "saslMechanism": security.sasl_mechanism,
                "securityProtocol": security.protocol,
                "timeoutSeconds": request.timeout_seconds,
                "topic": request.topic,
            },
            {
                "brokers": [item.get_secret_value() for item in request.brokers],
                "caCertificate": (
                    security.ca_certificate.get_secret_value()
                    if security.ca_certificate is not None
                    else None
                ),
                "password": (
                    security.password.get_secret_value() if security.password is not None else None
                ),
                "username": (
                    security.username.get_secret_value() if security.username is not None else None
                ),
            },
        )

    @staticmethod
    def _snapshot(connector: Any) -> dict[str, Any]:
        return {
            "connector_id": connector.connector_id,
            "connector_type": connector.connector_type,
            "name": connector.name,
            "enabled": connector.enabled,
            "safe_config": connector.safe_config,
            "created_at": connector.created_at,
            "updated_at": connector.updated_at,
        }

    @staticmethod
    def _not_found() -> LiveConnectorError:
        return LiveConnectorError("Live connector not found", "LIVE_CONNECTOR_NOT_FOUND", 404)
