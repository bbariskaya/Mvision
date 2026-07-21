import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import LiveCamera


class LiveCameraRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        name: str,
        uri_ciphertext: str,
        uri_fingerprint: str,
    ) -> LiveCamera:
        camera = LiveCamera(
            name=name,
            uri_ciphertext=uri_ciphertext,
            uri_fingerprint=uri_fingerprint,
            desired_state="stopped",
        )
        session.add(camera)
        await session.flush()
        return camera

    async def get(self, session: AsyncSession, camera_id: str) -> LiveCamera | None:
        stmt = select(LiveCamera).where(
            LiveCamera.camera_id == camera_id,
            LiveCamera.is_active.is_(True),
            LiveCamera.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_active(self, session: AsyncSession) -> list[LiveCamera]:
        stmt = (
            select(LiveCamera)
            .where(LiveCamera.is_active.is_(True), LiveCamera.deleted_at.is_(None))
            .order_by(LiveCamera.created_at, LiveCamera.camera_id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def set_desired(
        self, session: AsyncSession, camera_id: str, desired_state: str
    ) -> LiveCamera | None:
        if desired_state not in {"stopped", "running"}:
            raise ValueError("INVALID_LIVE_DESIRED_STATE")
        camera = await self.get(session, camera_id)
        if camera is None:
            return None
        camera.desired_state = desired_state
        await session.flush()
        return camera

    async def soft_delete(
        self, session: AsyncSession, camera_id: str, deleted_at: datetime.datetime
    ) -> LiveCamera | None:
        camera = await self.get(session, camera_id)
        if camera is None:
            return None
        camera.desired_state = "stopped"
        camera.is_active = False
        camera.deleted_at = deleted_at
        await session.flush()
        return camera
