import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import LiveDetectionEvent


class LiveEventRepository:
    async def create_once(
        self, session: AsyncSession, event: LiveDetectionEvent
    ) -> LiveDetectionEvent:
        values = {
            column.name: getattr(event, column.name)
            for column in LiveDetectionEvent.__table__.columns
            if column.name != "created_at"
        }
        stmt = (
            insert(LiveDetectionEvent)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    "run_id",
                    "native_track_id",
                    "identity_epoch",
                    "event_type",
                ]
            )
            .returning(LiveDetectionEvent.event_id)
        )
        inserted_id = (await session.execute(stmt)).scalar_one_or_none()
        if inserted_id is not None:
            inserted = await session.get(LiveDetectionEvent, inserted_id)
            assert inserted is not None
            return inserted
        existing_stmt = select(LiveDetectionEvent).where(
            LiveDetectionEvent.run_id == event.run_id,
            LiveDetectionEvent.native_track_id == event.native_track_id,
            LiveDetectionEvent.identity_epoch == event.identity_epoch,
            LiveDetectionEvent.event_type == event.event_type,
        )
        existing = (await session.execute(existing_stmt)).scalar_one()
        return existing

    async def list_page(
        self,
        session: AsyncSession,
        camera_id: str,
        *,
        limit: int,
        cursor_occurred_at: datetime.datetime | None = None,
        cursor_event_id: str | None = None,
    ) -> list[LiveDetectionEvent]:
        if limit <= 0:
            raise ValueError("INVALID_LIVE_EVENT_PAGE_LIMIT")
        stmt = select(LiveDetectionEvent).where(
            LiveDetectionEvent.camera_id == camera_id
        )
        if cursor_occurred_at is not None or cursor_event_id is not None:
            if cursor_occurred_at is None or cursor_event_id is None:
                raise ValueError("INVALID_LIVE_EVENT_CURSOR")
            stmt = stmt.where(
                or_(
                    LiveDetectionEvent.occurred_at < cursor_occurred_at,
                    and_(
                        LiveDetectionEvent.occurred_at == cursor_occurred_at,
                        LiveDetectionEvent.event_id < cursor_event_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            LiveDetectionEvent.occurred_at.desc(), LiveDetectionEvent.event_id.desc()
        ).limit(limit)
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, camera_id: str, event_id: str
    ) -> LiveDetectionEvent | None:
        stmt = select(LiveDetectionEvent).where(
            LiveDetectionEvent.camera_id == camera_id,
            LiveDetectionEvent.event_id == event_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
