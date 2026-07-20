import pytest

from app.services.exceptions import ValidationError
from app.services.image_validation import validate_jpeg


def test_accepts_complete_jpeg_marker_sequence():
    validate_jpeg(b"\xff\xd8payload\xff\xd9", 1024)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "EMPTY_IMAGE"),
        (b"not-jpeg", "INVALID_IMAGE"),
        (b"\xff\xd8truncated", "INVALID_IMAGE"),
    ],
)
def test_rejects_invalid_images(data, code):
    with pytest.raises(ValidationError) as caught:
        validate_jpeg(data, 1024)
    assert caught.value.error_code == code


def test_rejects_oversized_image():
    with pytest.raises(ValidationError) as caught:
        validate_jpeg(b"\xff\xd8payload\xff\xd9", 4)
    assert caught.value.error_code == "IMAGE_TOO_LARGE"
