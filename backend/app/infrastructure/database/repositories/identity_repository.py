from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import FaceIdentity


class FaceIdentityRepository:
    async def create(
        self,
        session: AsyncSession,
        face_id: str,
        lifecycle_status: str = "anonymous",
        name: str | None = None,
        metadata: dict | None = None,
    ) -> FaceIdentity:
        identity = FaceIdentity(
            face_id=face_id,
            lifecycle_status=lifecycle_status,
            name=name,
            metadata_=metadata or {},
        )
        session.add(identity)
        await session.flush()
        return identity

    async def get_by_id(self, session: AsyncSession, face_id: str) -> FaceIdentity | None:
        return await session.get(FaceIdentity, face_id)

    async def update_known(
        self,
        session: AsyncSession,
        face_id: str,
        name: str,
        metadata: dict | None = None,
    ) -> FaceIdentity | None:
        stmt = (
            update(FaceIdentity)
            .where(FaceIdentity.face_id == face_id)
            .values(
                lifecycle_status="known",
                name=name,
                metadata_=metadata or {},
                version=FaceIdentity.version + 1,
            )
            .returning(FaceIdentity)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, session: AsyncSession, face_id: str) -> FaceIdentity | None:
        stmt = (
            update(FaceIdentity)
            .where(FaceIdentity.face_id == face_id)
            .values(is_active=False, version=FaceIdentity.version + 1)
            .returning(FaceIdentity)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
