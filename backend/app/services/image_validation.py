from app.services.exceptions import ValidationError


def validate_jpeg(data: bytes, max_bytes: int) -> None:
    if not data:
        raise ValidationError("Uploaded image is empty", "EMPTY_IMAGE")
    if len(data) > max_bytes:
        raise ValidationError("Uploaded image exceeds the configured limit", "IMAGE_TOO_LARGE")
    if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValidationError("Uploaded file is not a complete JPEG image", "INVALID_IMAGE")
