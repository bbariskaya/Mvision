from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import VideoTrack


class VideoTrackRepository:
    async def delete_for_job(self, session: AsyncSession, job_id: str) -> None:
        await session.execute(delete(VideoTrack).where(VideoTrack.job_id == job_id))

    async def replace_for_job(
        self, session: AsyncSession, job_id: str, tracks: list[VideoTrack]
    ) -> list[VideoTrack]:
        await self.delete_for_job(session, job_id)
        session.add_all(tracks)
        await session.flush()
        return tracks

    async def list_by_job(self, session: AsyncSession, job_id: str) -> list[VideoTrack]:
        stmt = (
            select(VideoTrack)
            .where(VideoTrack.job_id == job_id)
            .order_by(VideoTrack.track_ordinal)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_by_face(self, session: AsyncSession, face_id: str) -> list[VideoTrack]:
        stmt = (
            select(VideoTrack)
            .where(VideoTrack.face_id == face_id)
            .order_by(VideoTrack.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())
