from dataclasses import dataclass

PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class ImageRequest:
    request_id: str
    encoded_jpeg: bytes
    protocol_version: int = PROTOCOL_VERSION


@dataclass(frozen=True)
class FaceDetection:
    ordinal: int
    x: float
    y: float
    width: float
    height: float
    landmarks_xy: tuple[float, ...]
    detector_confidence: float
    embedding: tuple[float, ...]
    aligned_jpeg: bytes


@dataclass(frozen=True)
class ImageResult:
    request_id: str
    status: str
    error_code: str
    faces: tuple[FaceDetection, ...]
