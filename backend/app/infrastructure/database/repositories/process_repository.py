from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ProcessRecord


class ProcessRecordRepository:
    async def create(
        self,
        session: AsyncSession,
        process_id: str,
        process_type: str,
        status: str = "started",
        face_count: int = 0,
        error_code: str | None = None,
        details: dict | None = None,
    ) -> ProcessRecord:
        record = ProcessRecord(
            process_id=process_id,
            process_type=process_type,
            status=status,
            face_count=face_count,
            error_code=error_code,
            details=details or {},
        )
        session.add(record)
        await session.flush()
        return record

    async def get_by_id(self, session: AsyncSession, process_id: str) -> ProcessRecord | None:
        return await session.get(ProcessRecord, process_id)

    async def complete(
        self,
        session: AsyncSession,
        process_id: str,
        face_count: int,
    ) -> ProcessRecord | None:
        stmt = (
            update(ProcessRecord)
            .where(ProcessRecord.process_id == process_id)
            .values(status="completed", face_count=face_count, completed_at=func.now())
            .returning(ProcessRecord)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def fail(
        self,
        session: AsyncSession,
        process_id: str,
        error_code: str,
    ) -> ProcessRecord | None:
        stmt = (
            update(ProcessRecord)
            .where(ProcessRecord.process_id == process_id)
            .values(status="failed", error_code=error_code, completed_at=func.now())
            .returning(ProcessRecord)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
