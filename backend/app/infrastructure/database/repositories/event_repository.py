from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ProcessEvent


class ProcessEventRepository:
    async def create(
        self,
        session: AsyncSession,
        process_id: str,
        event_type: str,
        sanitized_details: dict,
    ) -> ProcessEvent:
        event = ProcessEvent(
            process_id=process_id,
            event_type=event_type,
            sanitized_details=sanitized_details,
        )
        session.add(event)
        await session.flush()
        return event

    async def get_by_process(
        self,
        session: AsyncSession,
        process_id: str,
    ) -> list[ProcessEvent]:
        stmt = select(ProcessEvent).where(ProcessEvent.process_id == process_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
