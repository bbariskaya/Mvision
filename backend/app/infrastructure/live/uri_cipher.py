import hashlib
import hmac
import re
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr

_LIVE_URI_PATTERN = re.compile(r"\brtsps?://[^\s]+", re.IGNORECASE)
_MAX_URI_LENGTH = 4096
_MAX_SECRET_LENGTH = 6000


class LiveUriDecryptionError(ValueError):
    pass


def _validate_live_uri(uri: str) -> str:
    if not uri or len(uri) > _MAX_URI_LENGTH:
        raise ValueError("CAMERA_URI_INVALID")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in uri):
        raise ValueError("CAMERA_URI_INVALID")
    try:
        parsed = urlsplit(uri)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("CAMERA_URI_INVALID") from exc
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not hostname:
        raise ValueError("CAMERA_URI_INVALID")
    return uri


def redact_live_text(value: str) -> str:
    return _LIVE_URI_PATTERN.sub(
        lambda match: f"{match.group(0).split(':', 1)[0]}://[REDACTED]",
        value,
    )


class LiveUriCipher:
    def __init__(self, encryption_keys: list[str], fingerprint_key: str):
        if not encryption_keys or not fingerprint_key:
            raise ValueError("LIVE_URI_KEY_INVALID")
        try:
            fernets = [Fernet(key) for key in encryption_keys]
        except (TypeError, ValueError) as exc:
            raise ValueError("LIVE_URI_KEY_INVALID") from exc
        self._fernet = MultiFernet(fernets)
        self._fingerprint_key = fingerprint_key.encode("utf-8")

    def encrypt(self, uri: str) -> str:
        validated = _validate_live_uri(uri)
        return self._fernet.encrypt(validated.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> SecretStr:
        try:
            plaintext = self._fernet.decrypt(ciphertext).decode("utf-8")
            return SecretStr(_validate_live_uri(plaintext))
        except (InvalidToken, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise LiveUriDecryptionError("LIVE_URI_DECRYPTION_FAILED") from exc

    def fingerprint(self, uri: str) -> str:
        validated = _validate_live_uri(uri)
        return hmac.new(
            self._fingerprint_key,
            validated.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def encrypt_secret(self, value: str) -> str:
        if not value or len(value.encode("utf-8")) > _MAX_SECRET_LENGTH:
            raise ValueError("LIVE_SECRET_INVALID")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_secret(self, ciphertext: str) -> SecretStr:
        try:
            plaintext = self._fernet.decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, TypeError, UnicodeDecodeError) as exc:
            raise LiveUriDecryptionError("LIVE_SECRET_DECRYPTION_FAILED") from exc
        if not plaintext or len(plaintext.encode("utf-8")) > _MAX_SECRET_LENGTH:
            raise LiveUriDecryptionError("LIVE_SECRET_DECRYPTION_FAILED")
        return SecretStr(plaintext)
