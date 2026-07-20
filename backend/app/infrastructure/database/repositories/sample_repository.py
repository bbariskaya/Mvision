from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import FaceSample


class FaceSampleRepository:
    async def create_pending(
        self,
        session: AsyncSession,
        sample_id: str,
        face_id: str,
    ) -> FaceSample:
        sample = FaceSample(
            sample_id=sample_id,
            face_id=face_id,
            lifecycle_state="pending",
            bucket="",
            object_key=f"pending/{sample_id}",
            media_type="",
            sha256="",
            detector_version="",
            embedding_model_version="",
            alignment_version="",
            preprocess_version="",
            bounding_box={},
        )
        session.add(sample)
        await session.flush()
        return sample

    async def get_by_id(self, session: AsyncSession, sample_id: str) -> FaceSample | None:
        return await session.get(FaceSample, sample_id)

    async def update_blob_ready(
        self,
        session: AsyncSession,
        sample_id: str,
        bucket: str,
        object_key: str,
        media_type: str,
        sha256: str,
        detector_version: str,
        embedding_model_version: str,
        alignment_version: str,
        preprocess_version: str,
        bounding_box: dict,
        landmarks: dict | None = None,
        quality: dict | None = None,
    ) -> FaceSample | None:
        stmt = (
            update(FaceSample)
            .where(FaceSample.sample_id == sample_id)
            .values(
                lifecycle_state="blob_ready",
                bucket=bucket,
                object_key=object_key,
                media_type=media_type,
                sha256=sha256,
                detector_version=detector_version,
                embedding_model_version=embedding_model_version,
                alignment_version=alignment_version,
                preprocess_version=preprocess_version,
                bounding_box=bounding_box,
                landmarks=landmarks,
                quality=quality,
            )
            .returning(FaceSample)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active(self, session: AsyncSession, sample_id: str) -> FaceSample | None:
        stmt = (
            update(FaceSample)
            .where(FaceSample.sample_id == sample_id)
            .values(lifecycle_state="active", is_active=True)
            .returning(FaceSample)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_inactive(self, session: AsyncSession, sample_id: str) -> FaceSample | None:
        stmt = (
            update(FaceSample)
            .where(FaceSample.sample_id == sample_id)
            .values(lifecycle_state="inactive", is_active=False)
            .returning(FaceSample)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_failed(
        self,
        session: AsyncSession,
        sample_id: str,
        failure_code: str,
    ) -> FaceSample | None:
        stmt = (
            update(FaceSample)
            .where(FaceSample.sample_id == sample_id)
            .values(lifecycle_state="failed", failure_code=failure_code, is_active=False)
            .returning(FaceSample)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_face(
        self,
        session: AsyncSession,
        face_id: str,
        active_only: bool = False,
    ) -> list[FaceSample]:
        stmt = select(FaceSample).where(FaceSample.face_id == face_id)
        if active_only:
            stmt = stmt.where(FaceSample.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_active_by_model(
        self,
        session: AsyncSession,
        embedding_model_version: str,
        preprocess_version: str,
    ) -> list[FaceSample]:
        stmt = (
            select(FaceSample)
            .where(FaceSample.is_active.is_(True))
            .where(FaceSample.lifecycle_state == "active")
            .where(FaceSample.embedding_model_version == embedding_model_version)
            .where(FaceSample.preprocess_version == preprocess_version)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
