import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings

FERNET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_live_settings_expose_media_origins() -> None:
    settings = Settings(
        _env_file=None,
        live_api_key=SecretStr("test-key"),
        mediamtx_control_url="http://mediamtx:9997",
        mediamtx_internal_rtsp_origin="rtsp://mediamtx:8554",
    )

    assert settings.mediamtx_control_url == "http://mediamtx:9997"
    assert settings.mediamtx_internal_rtsp_origin == "rtsp://mediamtx:8554"
    assert settings.mediamtx_public_whip_origin == "http://localhost:8889"
    assert settings.mediamtx_public_rtsp_origin == "rtsp://localhost:8554"
    assert settings.mediamtx_public_webrtc_origin == "http://localhost:8889"
    assert settings.mediamtx_request_timeout_seconds == 3.0


def test_live_enabled_requires_internal_api_key() -> None:
    with pytest.raises(ValidationError, match="LIVE_SECRET_CONFIGURATION_REQUIRED"):
        Settings(
            _env_file=None,
            live_enabled=True,
            live_uri_encryption_keys=FERNET_KEY,
            live_uri_fingerprint_key="fingerprint-key",
        )


def test_live_api_key_remains_secret_in_settings_repr() -> None:
    settings = Settings(_env_file=None, live_api_key=SecretStr("do-not-log"))

    assert "do-not-log" not in repr(settings)


@pytest.mark.parametrize("value", ["0", "31"])
def test_mediamtx_timeout_is_bounded(monkeypatch, value: str) -> None:
    monkeypatch.setenv("MEDIAMTX_REQUEST_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
