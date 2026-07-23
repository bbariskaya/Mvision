from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.object_storage.exceptions import ObjectValidationError
from app.infrastructure.object_storage.minio_adapter import MinIOAdapter


class _Response:
    def __init__(self, data: bytes):
        self.data = data
        self.closed = False
        self.released = False

    def read(self):
        return self.data

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _Client:
    def __init__(self):
        self.response = _Response(b"range")
        self.upload = None

    def get_object(self, bucket, key, offset=0, length=0):
        self.get_args = (bucket, key, offset, length)
        return self.response

    def fput_object(self, bucket, key, path, **kwargs):
        self.upload = (bucket, key, path, kwargs)

    def stat_object(self, bucket, key):
        return SimpleNamespace(
            size=5,
            etag="etag",
            metadata={"X-Amz-Meta-Sha256": "a" * 64},
        )


def _adapter() -> MinIOAdapter:
    adapter = MinIOAdapter.__new__(MinIOAdapter)
    adapter._client = _Client()
    adapter._video_bucket = "mergenvision-videos"
    adapter._video_max_bytes = 500
    return adapter


@pytest.mark.asyncio
async def test_read_video_range_releases_minio_response():
    adapter = _adapter()
    key = "videos/019f8000-0000-7000-8000-000000000001/source"

    data = await adapter.read_video_range(key, offset=10, length=5)

    assert data == b"range"
    assert adapter._client.get_args == ("mergenvision-videos", key, 10, 5)
    assert adapter._client.response.closed is True
    assert adapter._client.response.released is True


@pytest.mark.asyncio
async def test_video_key_accepts_safe_configured_prefix():
    adapter = _adapter()
    key = "archive/input/019f8000-0000-7000-8000-000000000001/source"

    await adapter.read_video_range(key, offset=0, length=5)

    assert adapter._client.get_args == ("mergenvision-videos", key, 0, 5)


@pytest.mark.asyncio
async def test_upload_video_uses_hash_metadata(tmp_path: Path):
    adapter = _adapter()
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    key = "videos/019f8000-0000-7000-8000-000000000001/source"

    await adapter.upload_video(key, path, "video/mp4", "a" * 64)

    assert adapter._client.upload[0:3] == ("mergenvision-videos", key, str(path))
    assert adapter._client.upload[3]["metadata"]["X-Amz-Meta-Sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_video_key_rejects_path_traversal():
    adapter = _adapter()

    with pytest.raises(ObjectValidationError):
        await adapter.read_video_range("videos/../../secret", offset=0, length=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "/archive/019f8000-0000-7000-8000-000000000001/source",
        "archive//019f8000-0000-7000-8000-000000000001/source",
        "archive/not-a-uuid/source",
        "archive/019f8000-0000-7000-8000-000000000001/not-source",
        "archive/in put/019f8000-0000-7000-8000-000000000001/source",
    ],
)
async def test_video_key_rejects_unsafe_or_malformed_components(key):
    with pytest.raises(ObjectValidationError):
        await _adapter().read_video_range(key, offset=0, length=5)
