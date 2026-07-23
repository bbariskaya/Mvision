import datetime

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    LiveSession,
    LiveSessionGeneration,
    LiveSessionRun,
)

_TERMINAL_STATES = {"STOPPED", "FAILED"}
_NONTERMINAL_STATES = {"STARTING", "ACTIVE", "RECONNECTING", "STOPPING"}


class LiveSessionRepository:
    async def list_reconcilable(self, session: AsyncSession) -> list[LiveSessionGeneration]:
        stmt = (
            select(LiveSessionGeneration)
            .where(
                LiveSessionGeneration.desired_state == "running",
            )
            .order_by(
                LiveSessionGeneration.created_at,
                LiveSessionGeneration.generation_id,
            )
        )
        return list((await session.execute(stmt)).scalars().all())

    async def set_media_state(
        self,
        session: AsyncSession,
        generation_id: str,
        state: str,
        error_code: str | None = None,
    ) -> bool:
        if state not in {"provisioning", "waiting", "ready", "failed"}:
            raise ValueError("INVALID_LIVE_MEDIA_STATE")
        next_error = (
            error_code
            if error_code is not None
            else case(
                (
                    LiveSessionGeneration.error_code == "LIVE_MEDIA_PATH_FAILED",
                    None,
                ),
                else_=LiveSessionGeneration.error_code,
            )
        )
        stmt = (
            update(LiveSessionGeneration)
            .where(LiveSessionGeneration.generation_id == generation_id)
            .values(media_state=state, error_code=next_error)
            .returning(LiveSessionGeneration.generation_id)
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def create_session(
        self,
        session: AsyncSession,
        camera_external_id: str,
        location_snapshot: dict | None,
    ) -> LiveSession:
        live_session = LiveSession(
            camera_external_id=camera_external_id,
            location_snapshot=location_snapshot,
            desired_state="running",
            current_generation=1,
        )
        session.add(live_session)
        await session.flush()
        return live_session

    async def create_generation(
        self,
        session: AsyncSession,
        session_id: str,
        generation: int,
        requested_spec: dict,
        resolved_spec: dict,
        spec_hash: str,
        profile_id: str,
        profile_version: int,
        source_type: str,
        source_ciphertext: str | None,
        ingress_path: str,
    ) -> LiveSessionGeneration:
        parent_stmt = (
            select(LiveSession).where(LiveSession.session_id == session_id).with_for_update()
        )
        parent = (await session.execute(parent_stmt)).scalar_one_or_none()
        if parent is None:
            raise ValueError("LIVE_SESSION_NOT_FOUND")
        latest_stmt = (
            select(LiveSessionGeneration)
            .where(LiveSessionGeneration.session_id == session_id)
            .order_by(LiveSessionGeneration.generation.desc())
            .limit(1)
        )
        latest = (await session.execute(latest_stmt)).scalar_one_or_none()
        expected = 1 if latest is None else parent.current_generation + 1
        if generation != expected:
            raise ValueError("LIVE_GENERATION_CONFLICT")
        if latest is not None:
            latest.desired_state = "stopped"
            if latest.runtime_state not in _TERMINAL_STATES:
                latest.runtime_state = "STOPPING"
            parent.current_generation = generation
        generation_row = LiveSessionGeneration(
            session_id=session_id,
            generation=generation,
            requested_spec=requested_spec,
            resolved_spec=resolved_spec,
            spec_hash=spec_hash,
            profile_id=profile_id,
            profile_version=profile_version,
            source_type=source_type,
            source_ciphertext=source_ciphertext,
            ingress_path=ingress_path,
        )
        session.add(generation_row)
        await session.flush()
        return generation_row

    async def get(self, session: AsyncSession, session_id: str) -> LiveSession | None:
        return await session.get(LiveSession, session_id)

    async def get_current_generation(
        self, session: AsyncSession, session_id: str
    ) -> LiveSessionGeneration | None:
        stmt = (
            select(LiveSessionGeneration)
            .join(
                LiveSession,
                LiveSession.session_id == LiveSessionGeneration.session_id,
            )
            .where(
                LiveSession.session_id == session_id,
                LiveSessionGeneration.generation == LiveSession.current_generation,
            )
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_generation(
        self, session: AsyncSession, generation_id: str
    ) -> LiveSessionGeneration | None:
        return await session.get(LiveSessionGeneration, generation_id)

    async def list(self, session: AsyncSession) -> list[LiveSession]:
        stmt = select(LiveSession).order_by(LiveSession.created_at, LiveSession.session_id)
        return list((await session.execute(stmt)).scalars().all())

    async def set_desired_state(
        self,
        session: AsyncSession,
        session_id: str,
        desired_state: str,
        now: datetime.datetime,
    ) -> LiveSession | None:
        if desired_state not in {"running", "stopped"}:
            raise ValueError("INVALID_LIVE_DESIRED_STATE")
        stmt = select(LiveSession).where(LiveSession.session_id == session_id).with_for_update()
        live_session = (await session.execute(stmt)).scalar_one_or_none()
        if live_session is None:
            return None
        live_session.desired_state = desired_state
        live_session.stopped_at = now if desired_state == "stopped" else None
        generation_stmt = select(LiveSessionGeneration).where(
            LiveSessionGeneration.session_id == session_id,
            LiveSessionGeneration.generation == live_session.current_generation,
        )
        generation = (await session.execute(generation_stmt)).scalar_one_or_none()
        if generation is not None:
            generation.desired_state = desired_state
            if desired_state == "stopped" and generation.runtime_state not in _TERMINAL_STATES:
                generation.runtime_state = "STOPPING"
        await session.flush()
        return live_session

    async def claim_generation(
        self,
        session: AsyncSession,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        *,
        lease_seconds: int,
    ) -> LiveSessionRun | None:
        generation_stmt = (
            select(LiveSessionGeneration)
            .where(
                LiveSessionGeneration.desired_state == "running",
                LiveSessionGeneration.media_state == "ready",
            )
            .order_by(LiveSessionGeneration.created_at, LiveSessionGeneration.generation_id)
            .with_for_update(skip_locked=True)
        )
        generations = list((await session.execute(generation_stmt)).scalars().all())
        for generation in generations:
            latest_stmt = (
                select(LiveSessionRun)
                .where(LiveSessionRun.generation_id == generation.generation_id)
                .order_by(LiveSessionRun.runtime_attempt.desc())
                .with_for_update()
                .limit(1)
            )
            latest = (await session.execute(latest_stmt)).scalar_one_or_none()
            if latest is not None and latest.runtime_state not in _TERMINAL_STATES:
                if latest.lease_expires_at is not None and latest.lease_expires_at > now:
                    continue
                latest.runtime_state = "FAILED"
                latest.error_code = "LIVE_WORKER_LEASE_EXPIRED"
                latest.stopped_at = now
                latest.worker_id = None
                latest.lease_token = None
                latest.lease_expires_at = None
            attempt = 1 if latest is None else latest.runtime_attempt + 1
            run = LiveSessionRun(
                generation_id=generation.generation_id,
                runtime_attempt=attempt,
                runtime_state="STARTING",
                worker_id=worker_id,
                lease_token=lease_token,
                lease_expires_at=now + datetime.timedelta(seconds=lease_seconds),
                started_at=now,
            )
            generation.runtime_state = "STARTING"
            generation.started_at = generation.started_at or now
            session.add(run)
            await session.flush()
            return run
        return None

    async def renew_run(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        expires_at: datetime.datetime,
        *,
        generation_id: str,
        runtime_attempt: int,
    ) -> bool:
        stmt = (
            update(LiveSessionRun)
            .where(
                LiveSessionRun.run_id == run_id,
                LiveSessionRun.generation_id == generation_id,
                LiveSessionRun.runtime_attempt == runtime_attempt,
                LiveSessionRun.worker_id == worker_id,
                LiveSessionRun.lease_token == lease_token,
                LiveSessionRun.lease_expires_at > now,
            )
            .values(lease_expires_at=expires_at)
            .returning(LiveSessionRun.run_id)
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def update_run_state(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str | None,
        now: datetime.datetime,
        *,
        generation_id: str,
        runtime_attempt: int,
        runtime_state: str,
    ) -> bool:
        if runtime_state not in _NONTERMINAL_STATES:
            raise ValueError("INVALID_LIVE_RUNTIME_STATE")
        stmt = (
            update(LiveSessionRun)
            .where(
                LiveSessionRun.run_id == run_id,
                LiveSessionRun.generation_id == generation_id,
                LiveSessionRun.runtime_attempt == runtime_attempt,
                LiveSessionRun.worker_id == worker_id,
                LiveSessionRun.lease_token == lease_token,
                LiveSessionRun.lease_expires_at > now,
            )
            .values(runtime_state=runtime_state)
            .returning(LiveSessionRun.generation_id)
        )
        updated_generation_id = (await session.execute(stmt)).scalar_one_or_none()
        if updated_generation_id is None:
            return False
        generation = await session.get(LiveSessionGeneration, updated_generation_id)
        if generation is not None:
            generation.runtime_state = runtime_state
        await session.flush()
        return True

    async def finish_run(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str | None,
        now: datetime.datetime,
        *,
        generation_id: str,
        runtime_attempt: int,
        runtime_state: str,
        error_code: str | None = None,
    ) -> bool:
        if runtime_state not in _TERMINAL_STATES:
            raise ValueError("INVALID_LIVE_TERMINAL_STATE")
        stmt = (
            update(LiveSessionRun)
            .where(
                LiveSessionRun.run_id == run_id,
                LiveSessionRun.generation_id == generation_id,
                LiveSessionRun.runtime_attempt == runtime_attempt,
                LiveSessionRun.worker_id == worker_id,
                LiveSessionRun.lease_token == lease_token,
                LiveSessionRun.lease_expires_at > now,
            )
            .values(
                runtime_state=runtime_state,
                stopped_at=now,
                error_code=error_code,
                worker_id=None,
                lease_token=None,
                lease_expires_at=None,
            )
            .returning(LiveSessionRun.generation_id)
        )
        updated_generation_id = (await session.execute(stmt)).scalar_one_or_none()
        if updated_generation_id is None:
            return False
        generation = await session.get(LiveSessionGeneration, updated_generation_id)
        if generation is not None:
            generation.runtime_state = runtime_state
            generation.stopped_at = now
            generation.error_code = error_code
        await session.flush()
        return True
