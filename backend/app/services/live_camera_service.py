import datetime
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.models import LiveCamera, LiveCameraRun, LiveDetectionEvent
from app.infrastructure.database.repositories import (
    LiveCameraRepository,
    LiveEventRepository,
    LiveRunRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.live.uri_cipher import LiveUriCipher
from app.services.exceptions import LiveCameraError


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class LiveCameraService:
    def __init__(
        self,
        cameras: LiveCameraRepository,
        runs: LiveRunRepository,
        events: LiveEventRepository,
        cipher: LiveUriCipher | None,
        *,
        output_host: str,
        output_port: int,
        session_factory: SessionFactory = AsyncSessionLocal,
    ):
        self._cameras = cameras
        self._runs = runs
        self._events = events
        self._cipher = cipher
        self._output_host = output_host
        self._output_port = output_port
        self._session_factory = session_factory

    async def register(self, name: str, rtsp_uri: str) -> dict[str, Any]:
        if self._cipher is None:
            raise LiveCameraError(
                "Livestream URI encryption is unavailable",
                "LIVE_URI_ENCRYPTION_UNAVAILABLE",
                503,
            )
        selected_name = name.strip()
        if not selected_name:
            raise LiveCameraError("Camera name must not be empty", "CAMERA_NAME_INVALID", 422)
        ciphertext = self._cipher.encrypt(rtsp_uri)
        fingerprint = self._cipher.fingerprint(rtsp_uri)
        async with self._session_factory() as session:
            try:
                camera = await self._cameras.create(
                    session,
                    name=selected_name,
                    uri_ciphertext=ciphertext,
                    uri_fingerprint=fingerprint,
                )
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                constraint = self._constraint_name(exc)
                code = (
                    "CAMERA_NAME_CONFLICT"
                    if constraint == "uq_live_camera_active_name"
                    else "CAMERA_URI_CONFLICT"
                )
                raise LiveCameraError("Camera already exists", code, 409) from exc
            return self._camera_snapshot(camera, None)

    async def list(self) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            cameras = await self._cameras.list_active(session)
            return [
                self._camera_snapshot(
                    camera,
                    await self._runs.latest_for_camera(session, camera.camera_id),
                )
                for camera in cameras
            ]

    async def get(self, camera_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            camera = await self._required_camera(session, camera_id)
            run = await self._runs.latest_for_camera(session, camera_id)
            return self._camera_snapshot(camera, run)

    async def start(self, camera_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            try:
                camera = await self._cameras.set_desired(session, camera_id, "running")
                if camera is None:
                    raise LiveCameraError("Camera not found", "CAMERA_NOT_FOUND", 404)
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if self._constraint_name(exc) == "uq_live_single_running":
                    raise LiveCameraError(
                        "Another camera is already running",
                        "LIVE_CAMERA_LIMIT_REACHED",
                        409,
                    ) from exc
                raise
            run = await self._runs.latest_for_camera(session, camera_id)
            return self._camera_snapshot(camera, run)

    async def stop(self, camera_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            camera = await self._cameras.set_desired(session, camera_id, "stopped")
            if camera is None:
                raise LiveCameraError("Camera not found", "CAMERA_NOT_FOUND", 404)
            await session.commit()
            run = await self._runs.latest_for_camera(session, camera_id)
            return self._camera_snapshot(camera, run)

    async def delete(self, camera_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            camera = await self._cameras.soft_delete(
                session, camera_id, datetime.datetime.now(datetime.UTC)
            )
            if camera is None:
                raise LiveCameraError("Camera not found", "CAMERA_NOT_FOUND", 404)
            await session.commit()
            return {"camera_id": camera.camera_id, "deleted": True}

    async def events(self, camera_id: str, limit: int) -> dict[str, Any]:
        async with self._session_factory() as session:
            await self._required_camera(session, camera_id)
            events = await self._events.list_page(session, camera_id, limit=limit)
            return {
                "camera_id": camera_id,
                "events": [self._event_snapshot(event) for event in events],
                "next_cursor": None,
            }

    async def health(self, camera_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            camera = await self._required_camera(session, camera_id)
            run = await self._runs.latest_for_camera(session, camera_id)
            snapshot = self._camera_snapshot(camera, run)
            return {
                "camera_id": camera.camera_id,
                "run_id": run.run_id if run is not None else None,
                "generation": run.generation if run is not None else None,
                "desired_state": camera.desired_state,
                "runtime_state": snapshot["runtime_state"],
                "first_frame_at": run.first_frame_at if run is not None else None,
                "last_frame_at": run.last_frame_at if run is not None else None,
                "reconnect_count": run.reconnect_count if run is not None else 0,
                "metrics": run.metrics if run is not None else {},
                "output_url": snapshot["output_url"],
                "error_code": run.error_code if run is not None else None,
            }

    async def snapshot(self, camera_id: str, event_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            await self._required_camera(session, camera_id)
            event = await self._events.get(session, camera_id, event_id)
            if event is None:
                raise LiveCameraError("Live event not found", "LIVE_EVENT_NOT_FOUND", 404)
            raise LiveCameraError(
                "Live event snapshot is not available",
                "LIVE_SNAPSHOT_NOT_AVAILABLE",
                409,
            )

    async def _required_camera(self, session: Any, camera_id: str) -> LiveCamera:
        camera = await self._cameras.get(session, camera_id)
        if camera is None:
            raise LiveCameraError("Camera not found", "CAMERA_NOT_FOUND", 404)
        return camera

    def _camera_snapshot(
        self, camera: LiveCamera, run: LiveCameraRun | None
    ) -> dict[str, Any]:
        output_url = None
        if run is not None and run.output_path:
            path = run.output_path if run.output_path.startswith("/") else f"/{run.output_path}"
            output_url = f"rtsp://{self._output_host}:{self._output_port}{path}"
        return {
            "camera_id": camera.camera_id,
            "name": camera.name,
            "desired_state": camera.desired_state,
            "runtime_state": run.runtime_state if run is not None else "STOPPED",
            "output_url": output_url,
            "created_at": camera.created_at,
            "updated_at": camera.updated_at,
        }

    @staticmethod
    def _event_snapshot(event: LiveDetectionEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "native_track_id": event.native_track_id,
            "event_type": event.event_type,
            "face_id": event.face_id,
            "name": event.name_snapshot,
            "match_score": event.match_score,
            "nearest_known_score": event.nearest_known_score,
            "detector_confidence": event.detector_confidence,
            "first_seen_at": event.first_seen_at,
            "last_seen_at": event.last_seen_at,
            "occurred_at": event.occurred_at,
            "bounding_box": event.bounding_box,
            "landmarks": event.landmarks,
            "quality": event.quality,
            "snapshot_status": event.snapshot_status,
        }

    @staticmethod
    def _constraint_name(exc: IntegrityError) -> str | None:
        diagnostic = getattr(exc.orig, "diag", None)
        return getattr(diagnostic, "constraint_name", None)
