import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator

from app.presentation.schemas.live_sessions import StrictLiveApiModel

LiveEventType = Literal[
    "frame.result",
    "appearance.started",
    "appearance.ended",
    "session.state",
]


def _default_event_types() -> list[LiveEventType]:
    return ["frame.result"]


class WebhookNoAuth(StrictLiveApiModel):
    type: Literal["none"] = "none"


class WebhookBearerAuth(StrictLiveApiModel):
    type: Literal["bearer"]
    token: SecretStr = Field(min_length=1, max_length=4096)


WebhookAuth = Annotated[
    WebhookNoAuth | WebhookBearerAuth,
    Field(discriminator="type"),
]


class WebhookConnectorCreateRequest(StrictLiveApiModel):
    type: Literal["webhook"]
    name: str = Field(min_length=1, max_length=255)
    url: SecretStr = Field(min_length=1, max_length=4096)
    auth: WebhookAuth = Field(default_factory=WebhookNoAuth)
    event_types: list[LiveEventType] = Field(default_factory=_default_event_types, min_length=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
            raise ValueError("LIVE_CONNECTOR_CREDENTIAL_INVALID")
        try:
            parsed = urlsplit(raw)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("LIVE_CONNECTOR_CREDENTIAL_INVALID") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not hostname:
            raise ValueError("LIVE_CONNECTOR_CREDENTIAL_INVALID")
        return value


class KafkaSecurity(StrictLiveApiModel):
    protocol: Literal["plaintext", "ssl", "saslPlaintext", "saslSsl"] = "plaintext"
    sasl_mechanism: Literal["plain", "scramSha256", "scramSha512"] | None = None
    username: SecretStr | None = Field(default=None, max_length=1024)
    password: SecretStr | None = Field(default=None, max_length=4096)
    ca_certificate: SecretStr | None = Field(default=None, max_length=4096)


class KafkaConnectorCreateRequest(StrictLiveApiModel):
    type: Literal["kafka"]
    name: str = Field(min_length=1, max_length=255)
    brokers: list[SecretStr] = Field(min_length=1, max_length=32)
    topic: str = Field(min_length=1, max_length=249)
    security: KafkaSecurity = Field(default_factory=KafkaSecurity)
    acknowledgements: Literal["none", "leader", "all"] = "all"
    event_types: list[LiveEventType] = Field(default_factory=_default_event_types, min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


LiveConnectorCreateRequest = Annotated[
    WebhookConnectorCreateRequest | KafkaConnectorCreateRequest,
    Field(discriminator="type"),
]


class LiveConnectorResponse(StrictLiveApiModel):
    connector_id: str
    connector_type: Literal["webhook", "kafka"] = Field(alias="type")
    name: str
    enabled: bool
    safe_config: dict[str, Any]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class LiveConnectorListResponse(StrictLiveApiModel):
    connectors: list[LiveConnectorResponse]
