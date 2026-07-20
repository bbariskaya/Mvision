from dataclasses import dataclass


PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class ImageRequest:
    request_id: str
    encoded_jpeg: bytes
    protocol_version: int = PROTOCOL_VERSION
