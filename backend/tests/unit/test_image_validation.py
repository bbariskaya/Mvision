from io import BytesIO

from PIL import Image

from app.services.image_validation import normalize_image


def test_normalize_image_converts_png_to_jpeg():
    source = BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, 128)).save(source, format="PNG")

    result = normalize_image(source.getvalue(), "image/png", 1024)

    assert result.startswith(b"\xff\xd8")
    assert result.endswith(b"\xff\xd9")


def test_normalize_image_repairs_jpeg_without_end_marker():
    source = BytesIO()
    Image.new("RGB", (8, 8), (0, 255, 0)).save(source, format="JPEG")
    truncated = source.getvalue()[:-2]

    result = normalize_image(truncated, "image/jpeg", 4096)

    assert result.startswith(b"\xff\xd8")
    assert result.endswith(b"\xff\xd9")


def test_normalize_image_uses_content_signature_when_png_is_labeled_jpeg():
    source = BytesIO()
    Image.new("RGB", (2, 2), (0, 0, 255)).save(source, format="PNG")

    result = normalize_image(source.getvalue(), "image/jpeg", 1024)

    assert result.startswith(b"\xff\xd8")
    assert result.endswith(b"\xff\xd9")
