import base64

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.infrastructure.live.uri_cipher import (
    LiveUriCipher,
    LiveUriDecryptionError,
    redact_live_text,
)

TEST_FERNET_KEY = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
OLD_FERNET_KEY = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")
TEST_HMAC_KEY = "test-fingerprint-key"


def test_uri_round_trip_never_exposes_plaintext() -> None:
    cipher = LiveUriCipher([TEST_FERNET_KEY], TEST_HMAC_KEY)
    uri = "rtsp://alice:secret@10.0.0.12:554/live?token=hidden"

    encrypted = cipher.encrypt(uri)
    decrypted = cipher.decrypt(encrypted)

    assert uri not in encrypted
    assert decrypted.get_secret_value() == uri
    assert uri not in repr(decrypted)


def test_newest_key_encrypts_and_older_key_remains_decryptable() -> None:
    old_cipher = LiveUriCipher([OLD_FERNET_KEY], TEST_HMAC_KEY)
    rotated_cipher = LiveUriCipher(
        [TEST_FERNET_KEY, OLD_FERNET_KEY], TEST_HMAC_KEY
    )
    uri = "rtsps://camera.invalid/live"

    old_token = old_cipher.encrypt(uri)
    new_token = rotated_cipher.encrypt(uri)

    assert rotated_cipher.decrypt(old_token).get_secret_value() == uri
    with pytest.raises(LiveUriDecryptionError, match="LIVE_URI_DECRYPTION_FAILED"):
        old_cipher.decrypt(new_token)


def test_redactor_removes_userinfo_query_and_host() -> None:
    text = "connect rtsp://alice:secret@10.0.0.12/live?token=hidden failed"

    assert redact_live_text(text) == "connect rtsp://[REDACTED] failed"


@pytest.mark.parametrize(
    "uri",
    [
        "http://camera.invalid/live",
        "rtsp:///live",
        "rtsp://camera.invalid/live\nforged",
        "rtsp://camera.invalid/" + "a" * 4096,
    ],
)
def test_encrypt_rejects_invalid_uri(uri: str) -> None:
    cipher = LiveUriCipher([TEST_FERNET_KEY], TEST_HMAC_KEY)

    with pytest.raises(ValueError, match="CAMERA_URI_INVALID"):
        cipher.encrypt(uri)


def test_invalid_fernet_key_is_rejected_without_echoing_key() -> None:
    invalid_key = "not-a-fernet-key"

    with pytest.raises(ValueError) as error:
        LiveUriCipher([invalid_key], TEST_HMAC_KEY)

    assert invalid_key not in str(error.value)


def test_tampered_ciphertext_returns_stable_sanitized_error() -> None:
    cipher = LiveUriCipher([TEST_FERNET_KEY], TEST_HMAC_KEY)
    token = cipher.encrypt("rtsp://camera.invalid/live")
    tampered = token[:-2] + "aa"

    with pytest.raises(LiveUriDecryptionError) as error:
        cipher.decrypt(tampered)

    assert str(error.value) == "LIVE_URI_DECRYPTION_FAILED"
    assert tampered not in str(error.value)


def test_fingerprint_is_stable_and_keyed() -> None:
    uri = "rtsp://camera.invalid/live"
    first = LiveUriCipher([TEST_FERNET_KEY], TEST_HMAC_KEY)
    second = LiveUriCipher([TEST_FERNET_KEY], "different-fingerprint-key")

    assert first.fingerprint(uri) == first.fingerprint(uri)
    assert first.fingerprint(uri) != second.fingerprint(uri)
    assert uri not in first.fingerprint(uri)


def test_live_settings_require_both_secret_sets_when_enabled() -> None:
    with pytest.raises(ValidationError, match="LIVE_SECRET_CONFIGURATION_REQUIRED"):
        Settings(_env_file=None, live_enabled=True)


def test_live_settings_accept_configured_secrets() -> None:
    settings = Settings(
        _env_file=None,
        live_enabled=True,
        live_uri_encryption_keys=TEST_FERNET_KEY,
        live_uri_fingerprint_key=TEST_HMAC_KEY,
    )

    assert settings.live_enabled is True
    assert settings.live_worker_id == "live-worker-0"
    assert settings.live_rtsp_output_port == 8554
