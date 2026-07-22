import datetime
import secrets

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import LiveCamera, LiveCameraRun

_TERMINAL_STATES = {"STOPPED", "FAILED"}


class LiveRunRepository:
    async def claim(
        self,
        session: AsyncSession,
        camera_id: str | None,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        lease_seconds: int,
    ) -> LiveCameraRun | None:
        camera_stmt = (
            select(LiveCamera)
            .where(
                LiveCamera.desired_state == "running",
                LiveCamera.is_active.is_(True),
                LiveCamera.deleted_at.is_(None),
            )
            .order_by(LiveCamera.updated_at, LiveCamera.camera_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if camera_id is not None:
            camera_stmt = camera_stmt.where(LiveCamera.camera_id == camera_id)
        camera = (await session.execute(camera_stmt)).scalar_one_or_none()
        if camera is None:
            return None

        latest_stmt = (
            select(LiveCameraRun)
            .where(LiveCameraRun.camera_id == camera.camera_id)
            .order_by(LiveCameraRun.generation.desc())
            .with_for_update()
            .limit(1)
        )
        latest = (await session.execute(latest_stmt)).scalar_one_or_none()
        if latest is not None and latest.runtime_state not in _TERMINAL_STATES:
            if latest.lease_expires_at is not None and latest.lease_expires_at > now:
                return None
            latest.runtime_state = "FAILED"
            latest.stopped_at = now
            latest.error_code = "LIVE_WORKER_LEASE_EXPIRED"
            latest.worker_id = None
            latest.lease_token = None
            latest.lease_expires_at = None

        run = LiveCameraRun(
            camera_id=camera.camera_id,
            generation=1 if latest is None else latest.generation + 1,
            runtime_state="STARTING",
            worker_id=worker_id,
            lease_token=lease_token,
            lease_expires_at=now + datetime.timedelta(seconds=lease_seconds),
            started_at=now,
            traceparent=camera.desired_traceparent or self._new_traceparent(),
            tracestate=camera.desired_tracestate,
        )
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    def _new_traceparent() -> str:
        return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"

    async def renew(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        expires_at: datetime.datetime,
    ) -> bool:
        return await self._fenced_update(
            session,
            run_id,
            worker_id,
            lease_token,
            now,
            {"lease_expires_at": expires_at},
        )

    async def update_state(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        *,
        runtime_state: str,
        first_frame_at: datetime.datetime | None = None,
        last_frame_at: datetime.datetime | None = None,
        reconnect_count: int | None = None,
        output_path: str | None = None,
        error_code: str | None = None,
        sanitized_error: str | None = None,
    ) -> bool:
        values: dict = {"runtime_state": runtime_state}
        for key, value in (
            ("first_frame_at", first_frame_at),
            ("last_frame_at", last_frame_at),
            ("reconnect_count", reconnect_count),
            ("output_path", output_path),
            ("error_code", error_code),
            ("sanitized_error", sanitized_error),
        ):
            if value is not None:
                values[key] = value
        return await self._fenced_update(
            session, run_id, worker_id, lease_token, now, values
        )

    async def update_metrics(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        metrics: dict,
    ) -> bool:
        return await self._fenced_update(
            session,
            run_id,
            worker_id,
            lease_token,
            now,
            {"metrics": metrics},
        )

    async def finish(
        self,
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        *,
        runtime_state: str,
        error_code: str | None = None,
        sanitized_error: str | None = None,
    ) -> bool:
        if runtime_state not in _TERMINAL_STATES:
            raise ValueError("INVALID_LIVE_TERMINAL_STATE")
        return await self._fenced_update(
            session,
            run_id,
            worker_id,
            lease_token,
            now,
            {
                "runtime_state": runtime_state,
                "stopped_at": now,
                "error_code": error_code,
                "sanitized_error": sanitized_error,
                "worker_id": None,
                "lease_token": None,
                "lease_expires_at": None,
            },
        )

    async def latest_for_camera(
        self, session: AsyncSession, camera_id: str
    ) -> LiveCameraRun | None:
        stmt = (
            select(LiveCameraRun)
            .where(LiveCameraRun.camera_id == camera_id)
            .order_by(LiveCameraRun.generation.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _fenced_update(
        session: AsyncSession,
        run_id: str,
        worker_id: str,
        lease_token: str,
        now: datetime.datetime,
        values: dict,
    ) -> bool:
        stmt = (
            update(LiveCameraRun)
            .where(
                LiveCameraRun.run_id == run_id,
                LiveCameraRun.worker_id == worker_id,
                LiveCameraRun.lease_token == lease_token,
                LiveCameraRun.lease_expires_at > now,
            )
            .values(**values)
            .returning(LiveCameraRun.run_id)
        )
        updated = (await session.execute(stmt)).scalar_one_or_none()
        await session.flush()
        return updated is not None
