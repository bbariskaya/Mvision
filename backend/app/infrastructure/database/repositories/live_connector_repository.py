from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import LiveConnector


class LiveConnectorRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        connector_type: str,
        name: str,
        safe_config: dict,
        secret_ciphertext: str | None,
    ) -> LiveConnector:
        connector = LiveConnector(
            connector_type=connector_type,
            name=name,
            safe_config=safe_config,
            secret_ciphertext=secret_ciphertext,
        )
        session.add(connector)
        await session.flush()
        return connector

    async def get(
        self, session: AsyncSession, connector_id: str
    ) -> LiveConnector | None:
        return await session.get(LiveConnector, connector_id)

    async def list(self, session: AsyncSession) -> list[LiveConnector]:
        stmt = select(LiveConnector).order_by(
            LiveConnector.created_at, LiveConnector.connector_id
        )
        return list((await session.execute(stmt)).scalars().all())

    async def disable(
        self, session: AsyncSession, connector_id: str
    ) -> LiveConnector | None:
        connector = await self.get(session, connector_id)
        if connector is None:
            return None
        connector.enabled = False
        await session.flush()
        return connector
