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
        self._max_bytes = settings.aligned_sample_max_bytes
        self._video_max_bytes = settings.video_max_upload_bytes

    async def ensure_bucket(self) -> None:
        for bucket in (self._bucket, self._video_bucket):
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
