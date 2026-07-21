from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.services.exceptions import ValidationError


def validate_jpeg(data: bytes, max_bytes: int) -> None:
    if not data:
        raise ValidationError("Uploaded image is empty", "EMPTY_IMAGE")
    if len(data) > max_bytes:
        raise ValidationError("Uploaded image exceeds the configured limit", "IMAGE_TOO_LARGE")
    if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValidationError("Uploaded file is not a complete JPEG image", "INVALID_IMAGE")


def normalize_image(data: bytes, content_type: str, max_bytes: int) -> bytes:
    if not data:
        raise ValidationError("Uploaded image is empty", "EMPTY_IMAGE")
    if len(data) > max_bytes:
        raise ValidationError("Uploaded image exceeds the configured limit", "IMAGE_TOO_LARGE")
    if content_type not in {"image/jpeg", "image/jpg", "image/png"}:
        raise ValidationError("Only JPEG and PNG images are supported", "UNSUPPORTED_MEDIA_TYPE")
    if data.startswith(b"\xff\xd8") and not data.endswith(b"\xff\xd9"):
        data += b"\xff\xd9"
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValidationError(
                    "Only JPEG and PNG images are supported", "UNSUPPORTED_MEDIA_TYPE"
                )
            image.load()
            converted = image.convert("RGB")
            output = BytesIO()
            converted.save(output, format="JPEG", quality=95)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("Uploaded file is not a valid image", "INVALID_IMAGE") from exc
    normalized = output.getvalue()
    if len(normalized) > max_bytes:
        raise ValidationError("Uploaded image exceeds the configured limit", "IMAGE_TOO_LARGE")
    return normalized
