import asyncio
import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from minio import Minio
from minio.error import S3Error

from app.config import Settings
from app.infrastructure.object_storage.exceptions import (
    ObjectNotFoundError,
    ObjectStorageError,
    ObjectValidationError,
)

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
OBJECT_KEY_PATTERN = re.compile(
    r"^faces/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/aligned$"
)
VIDEO_OBJECT_KEY_PATTERN = re.compile(
    r"^videos/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/source$"
)
LIVE_OBJECT_KEY_PATTERN = re.compile(
    r"^live/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}/aligned$"
)


@dataclass(frozen=True)
class ObjectInfo:
    bucket: str
    object_key: str
    size: int
    etag: str
    metadata: dict
    sha256: str | None


class MinIOAdapter:
    def __init__(self, settings: Settings):
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket_faces
        self._video_bucket = settings.minio_bucket_videos
        self._live_bucket = settings.minio_bucket_live
        self._max_bytes = settings.aligned_sample_max_bytes
        self._video_max_bytes = settings.video_max_upload_bytes

    async def ensure_bucket(self) -> None:
        for bucket in (self._bucket, self._video_bucket, self._live_bucket):
            exists = await asyncio.to_thread(self._client.bucket_exists, bucket)
            if not exists:
                await asyncio.to_thread(self._client.make_bucket, bucket)

    def _validate_object_key(self, object_key: str) -> None:
        if not OBJECT_KEY_PATTERN.match(object_key):
            raise ObjectValidationError("Invalid object key format")

    def _validate_media_type(self, media_type: str) -> None:
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise ObjectValidationError(f"Unsupported media type: {media_type}")

    def _validate_size(self, data: bytes) -> None:
        if len(data) > self._max_bytes:
            raise ObjectValidationError("Aligned sample exceeds size limit")

    async def upload_aligned_sample(
        self,
        object_key: str,
        data: bytes,
        media_type: str,
        sample_id: str,
    ) -> str:
        self._validate_object_key(object_key)
        self._validate_media_type(media_type)
        self._validate_size(data)

        sha256 = hashlib.sha256(data).hexdigest()
        metadata: dict[str, Any] = {
            "X-Amz-Meta-Sample-Id": sample_id,
            "X-Amz-Meta-Sha256": sha256,
        }
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            object_key,
            BytesIO(data),
            len(data),
            content_type=media_type,
            metadata=metadata,
        )
        return sha256

    async def stat_aligned_sample(self, object_key: str) -> ObjectInfo:
        self._validate_object_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.stat_object,
                self._bucket,
                object_key,
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc

        meta = response.metadata or {}
        return ObjectInfo(
            bucket=self._bucket,
            object_key=object_key,
            size=response.size or 0,
            etag=response.etag or "",
            metadata=dict(meta),
            sha256=meta.get("X-Amz-Meta-Sha256") or meta.get("x-amz-meta-sha256"),
        )

    async def get_aligned_sample(self, object_key: str) -> tuple[bytes, ObjectInfo]:
        self._validate_object_key(object_key)
        info = await self.stat_aligned_sample(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                self._bucket,
                object_key,
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc

        data = await asyncio.to_thread(response.read)
        return data, info

    async def delete_aligned_sample(self, object_key: str) -> None:
        self._validate_object_key(object_key)
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, object_key)
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc

    async def upload_live_snapshot(
        self, object_key: str, data: bytes, event_id: str
    ) -> ObjectInfo:
        self._validate_live_snapshot(object_key, data)
        sha256 = hashlib.sha256(data).hexdigest()
        try:
            await asyncio.to_thread(
                self._client.put_object,
                self._live_bucket,
                object_key,
                BytesIO(data),
                len(data),
                content_type="image/jpeg",
                metadata={
                    "X-Amz-Meta-Event-Id": event_id,
                    "X-Amz-Meta-Sha256": sha256,
                },
            )
            return await self.stat_live_snapshot(object_key)
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc

    async def stat_live_snapshot(self, object_key: str) -> ObjectInfo:
        self._validate_live_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.stat_object, self._live_bucket, object_key
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc
        metadata = dict(response.metadata or {})
        return ObjectInfo(
            bucket=self._live_bucket,
            object_key=object_key,
            size=response.size or 0,
            etag=response.etag or "",
            metadata=metadata,
            sha256=metadata.get("X-Amz-Meta-Sha256")
            or metadata.get("x-amz-meta-sha256"),
        )

    async def get_live_snapshot(self, object_key: str) -> tuple[bytes, ObjectInfo]:
        info = await self.stat_live_snapshot(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, self._live_bucket, object_key
            )
            data = await asyncio.to_thread(response.read)
            await asyncio.to_thread(response.close)
            await asyncio.to_thread(response.release_conn)
            return data, info
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc

    async def delete_live_snapshot(self, object_key: str) -> None:
        self._validate_live_key(object_key)
        try:
            await asyncio.to_thread(
                self._client.remove_object, self._live_bucket, object_key
            )
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc

    @staticmethod
    def _validate_live_key(object_key: str) -> None:
        if not LIVE_OBJECT_KEY_PATTERN.fullmatch(object_key):
            raise ObjectValidationError("Invalid live snapshot key format")

    @classmethod
    def _validate_live_snapshot(cls, object_key: str, data: bytes) -> None:
        cls._validate_live_key(object_key)
        if len(data) > 512 * 1024:
            raise ObjectValidationError("Live snapshot exceeds size limit")
        if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
            raise ObjectValidationError("Live snapshot is not a JPEG")
        index = 2
        sof_markers = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while index + 8 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in sof_markers:
                height = int.from_bytes(data[index + 5 : index + 7])
                width = int.from_bytes(data[index + 7 : index + 9])
                if (width, height) != (112, 112):
                    raise ObjectValidationError("Live snapshot must be 112x112")
                return
            if index + 4 > len(data):
                break
            segment_size = int.from_bytes(data[index + 2 : index + 4])
            if segment_size < 2:
                break
            index += 2 + segment_size
        raise ObjectValidationError("Live snapshot dimensions are unavailable")

    def _validate_video_key(self, object_key: str) -> None:
        if not VIDEO_OBJECT_KEY_PATTERN.fullmatch(object_key):
            raise ObjectValidationError("Invalid video object key format")

    async def upload_video(
        self,
        object_key: str,
        path: Path,
        media_type: str,
        sha256: str,
    ) -> ObjectInfo:
        self._validate_video_key(object_key)
        size = path.stat().st_size
        if size <= 0 or size > self._video_max_bytes:
            raise ObjectValidationError("Video size is outside the configured limit")
        try:
            await asyncio.to_thread(
                self._client.fput_object,
                self._video_bucket,
                object_key,
                str(path),
                content_type=media_type,
                metadata={"X-Amz-Meta-Sha256": sha256},
            )
            return await self.stat_video(object_key)
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc

    async def stat_video(self, object_key: str) -> ObjectInfo:
        self._validate_video_key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.stat_object, self._video_bucket, object_key
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc
        metadata = dict(response.metadata or {})
        return ObjectInfo(
            bucket=self._video_bucket,
            object_key=object_key,
            size=response.size or 0,
            etag=response.etag or "",
            metadata=metadata,
            sha256=metadata.get("X-Amz-Meta-Sha256")
            or metadata.get("x-amz-meta-sha256"),
        )

    async def download_video(self, object_key: str, destination: Path) -> None:
        self._validate_video_key(object_key)
        try:
            await asyncio.to_thread(
                self._client.fget_object,
                self._video_bucket,
                object_key,
                str(destination),
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc

    async def read_video_range(self, object_key: str, offset: int, length: int) -> bytes:
        self._validate_video_key(object_key)
        if offset < 0 or length <= 0:
            raise ObjectValidationError("Invalid video byte range")
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                self._video_bucket,
                object_key,
                offset=offset,
                length=length,
            )
            try:
                return await asyncio.to_thread(response.read)
            finally:
                await asyncio.to_thread(response.close)
                await asyncio.to_thread(response.release_conn)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(object_key) from exc
            raise ObjectStorageError(str(exc)) from exc

    async def delete_video(self, object_key: str) -> None:
        self._validate_video_key(object_key)
        try:
            await asyncio.to_thread(
                self._client.remove_object, self._video_bucket, object_key
            )
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc
