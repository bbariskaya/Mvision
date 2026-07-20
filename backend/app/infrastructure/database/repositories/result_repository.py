from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import RecognitionResult


class RecognitionResultRepository:
    async def create(
        self,
        session: AsyncSession,
        result_id: str,
        process_id: str,
        detection_ordinal: int,
        face_id: str,
        status_snapshot: str,
        name_snapshot: str | None,
        metadata_snapshot: dict,
        bounding_box: dict,
        detector_confidence: float,
        match_confidence: float,
        matched_sample_id: str | None = None,
    ) -> RecognitionResult:
        result = RecognitionResult(
            result_id=result_id,
            process_id=process_id,
            detection_ordinal=detection_ordinal,
            face_id=face_id,
            status_snapshot=status_snapshot,
            name_snapshot=name_snapshot,
            metadata_snapshot=metadata_snapshot,
            bounding_box=bounding_box,
            detector_confidence=detector_confidence,
            match_confidence=match_confidence,
            matched_sample_id=matched_sample_id,
        )
        session.add(result)
        await session.flush()
        return result

    async def get_by_process(
        self,
        session: AsyncSession,
        process_id: str,
    ) -> list[RecognitionResult]:
        stmt = (
            select(RecognitionResult)
            .where(RecognitionResult.process_id == process_id)
            .order_by(RecognitionResult.detection_ordinal)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_face(
        self,
        session: AsyncSession,
        face_id: str,
    ) -> list[RecognitionResult]:
        stmt = (
            select(RecognitionResult)
            .where(RecognitionResult.face_id == face_id)
            .order_by(RecognitionResult.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
