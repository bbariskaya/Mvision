import datetime
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.database.repositories.live_connector_repository import (
    LiveConnectorRepository,
)
from app.infrastructure.database.repositories.live_session_repository import (
    LiveSessionRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.media.mediamtx_client import MediaMtxError
from app.presentation.schemas.live_sessions import (
    LiveSessionCreateRequest,
    LiveSessionReconfigureRequest,
    RtspPullSource,
    WhepPullSource,
)
from app.services.exceptions import LiveSessionError
from app.services.live_session_compiler import (
    LiveSessionCompiler,
    ResolvedLiveSessionSpec,
)


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class SecretCipher(Protocol):
    def encrypt_secret(self, value: str) -> str: ...


class Reconciler(Protocol):
    async def reconcile(self) -> Any: ...


class LiveSessionService:
    def __init__(
        self,
        settings: Settings,
        sessions: LiveSessionRepository,
        connectors: LiveConnectorRepository,
        compiler: LiveSessionCompiler,
        cipher: SecretCipher | None,
        reconciler: Reconciler,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
        clock: Callable[[], datetime.datetime] | None = None,
    ):
        self._settings = settings
        self._sessions = sessions
        self._connectors = connectors
        self._compiler = compiler
        self._cipher = cipher
        self._reconciler = reconciler
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.datetime.now(datetime.UTC))

    async def create(self, request: LiveSessionCreateRequest) -> dict[str, Any]:
        resolved = self._compile(request)
        source_ciphertext = self._encrypt_source(request)
        ingress_path = f"ingress/{new_uuid7()}"
        async with self._session_factory() as session:
            try:
                await self._validate_connectors(session, resolved)
                live_session = await self._sessions.create_session(
                    session,
                    request.camera_id,
                    self._location_snapshot(request),
                )
                await self._sessions.create_generation(
                    session,
                    session_id=live_session.session_id,
                    generation=1,
                    requested_spec=self._safe_request_snapshot(request),
                    resolved_spec=asdict(resolved),
                    spec_hash=resolved.spec_hash,
                    profile_id=resolved.profile_id,
                    profile_version=resolved.profile_version,
                    source_type=resolved.source_type,
                    source_ciphertext=source_ciphertext,
                    ingress_path=ingress_path,
                )
                await session.commit()
            except LiveSessionError:
                await session.rollback()
                raise
            except IntegrityError as exc:
                await session.rollback()
                raise LiveSessionError(
                    "Live session conflicts with existing state",
                    "LIVE_GENERATION_CONFLICT",
                    409,
                ) from exc
        await self._reconcile_safely()
        return await self._load_snapshot(live_session.session_id, include_publish_url=True)

    async def get(self, session_id: str) -> dict[str, Any]:
        return await self._load_snapshot(session_id, include_publish_url=False)

    async def list(self) -> dict[str, Any]:
        async with self._session_factory() as session:
            parents = await self._sessions.list(session)
            values = []
            for parent in parents:
                generation = await self._sessions.get_current_generation(session, parent.session_id)
                if generation is not None:
                    values.append(self._snapshot(parent, generation, False))
            return {"sessions": values}

    async def reconfigure(
        self, session_id: str, request: LiveSessionReconfigureRequest
    ) -> dict[str, Any]:
        resolved = self._compile(request)
        source_ciphertext = self._encrypt_source(request)
        async with self._session_factory() as session:
            parent = await self._sessions.get(session, session_id)
            if parent is None:
                raise self._not_found()
            if parent.desired_state != "running":
                raise LiveSessionError(
                    "Stopped live session cannot be reconfigured",
                    "LIVE_SESSION_SPEC_INVALID",
                    409,
                )
            try:
                await self._validate_connectors(session, resolved)
                await self._sessions.create_generation(
                    session,
                    session_id=session_id,
                    generation=parent.current_generation + 1,
                    requested_spec=self._safe_request_snapshot(request),
                    resolved_spec=asdict(resolved),
                    spec_hash=resolved.spec_hash,
                    profile_id=resolved.profile_id,
                    profile_version=resolved.profile_version,
                    source_type=resolved.source_type,
                    source_ciphertext=source_ciphertext,
                    ingress_path=f"ingress/{new_uuid7()}",
                )
                await session.commit()
            except LiveSessionError:
                await session.rollback()
                raise
            except (IntegrityError, ValueError) as exc:
                await session.rollback()
                raise LiveSessionError(
                    "Live session reconfiguration conflicted",
                    "LIVE_GENERATION_CONFLICT",
                    409,
                ) from exc
        await self._reconcile_safely()
        return await self._load_snapshot(session_id, include_publish_url=True)

    async def stop(self, session_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            parent = await self._sessions.set_desired_state(
                session, session_id, "stopped", self._clock()
            )
            if parent is None:
                raise self._not_found()
            await session.commit()
        await self._reconcile_safely()
        return await self._load_snapshot(session_id, include_publish_url=False)

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema_versions": [1],
            "profiles": [
                {
                    "id": self._settings.live_profile_id,
                    "version": self._settings.live_profile_version,
                }
            ],
            "source_types": ["rtspPull", "whepPull", "whipPush"],
            "processing_modes": ["detect", "detectTrack", "recognize"],
            "sampling_modes": ["everyNFrames", "framesPerSecond"],
            "connector_types": ["webhook", "kafka"],
            "max_concurrent_sessions": 1,
        }

    def _compile(
        self, request: LiveSessionCreateRequest | LiveSessionReconfigureRequest
    ) -> ResolvedLiveSessionSpec:
        try:
            return self._compiler.compile(request)
        except ValueError as exc:
            code = str(exc)
            if code not in {
                "LIVE_PROFILE_NOT_FOUND",
                "LIVE_JSON_SINK_REQUIRED",
                "LIVE_SESSION_SPEC_INVALID",
            }:
                code = "LIVE_SESSION_SPEC_INVALID"
            raise LiveSessionError("Invalid live session specification", code, 422) from exc

    def _encrypt_source(
        self, request: LiveSessionCreateRequest | LiveSessionReconfigureRequest
    ) -> str | None:
        if not isinstance(request.source, (RtspPullSource, WhepPullSource)):
            return None
        if self._cipher is None:
            raise LiveSessionError(
                "Live source encryption is unavailable",
                "LIVE_SECRET_CONFIGURATION_REQUIRED",
                503,
            )
        try:
            return self._cipher.encrypt_secret(request.source.url.get_secret_value())
        except ValueError as exc:
            raise LiveSessionError(
                "Invalid live source credential",
                "LIVE_SOURCE_CREDENTIAL_INVALID",
                422,
            ) from exc

    async def _validate_connectors(self, session: Any, resolved: ResolvedLiveSessionSpec) -> None:
        if len(set(resolved.json.connector_refs)) != len(resolved.json.connector_refs):
            raise LiveSessionError(
                "Connector references must be unique",
                "LIVE_SESSION_SPEC_INVALID",
                422,
            )
        for connector_id in resolved.json.connector_refs:
            connector = await self._connectors.get(session, connector_id)
            if connector is None or not connector.enabled:
                raise LiveSessionError(
                    "Live connector not found",
                    "LIVE_CONNECTOR_NOT_FOUND",
                    404,
                )

    async def _reconcile_safely(self) -> None:
        try:
            await self._reconciler.reconcile()
        except MediaMtxError:
            # Durable desired state remains available to the periodic reconciler.
            return

    async def _load_snapshot(self, session_id: str, *, include_publish_url: bool) -> dict[str, Any]:
        async with self._session_factory() as session:
            parent = await self._sessions.get(session, session_id)
            generation = await self._sessions.get_current_generation(session, session_id)
            if parent is None or generation is None:
                raise self._not_found()
            return self._snapshot(parent, generation, include_publish_url)

    def _snapshot(self, parent: Any, generation: Any, include_publish_url: bool) -> dict[str, Any]:
        state = self._public_state(generation)
        publish_url = None
        if include_publish_url and generation.source_type == "whipPush":
            publish_url = (
                f"{self._settings.mediamtx_public_whip_origin.rstrip('/')}"
                f"/{generation.ingress_path}/whip"
            )
        recording_enabled = bool(
            generation.resolved_spec.get("recording", {}).get("enabled", False)
        )
        annotated_enabled = bool(
            generation.resolved_spec.get("annotated_stream", {}).get("enabled", False)
        )
        return {
            "session_id": parent.session_id,
            "generation": generation.generation,
            "state": state,
            "camera_id": parent.camera_external_id,
            "location": parent.location_snapshot,
            "profile": {
                "id": generation.profile_id,
                "version": generation.profile_version,
            },
            "ingest": {
                "type": generation.source_type,
                "publish_url": publish_url,
            },
            "links": {
                "frames": f"/api/v1/live/sessions/{parent.session_id}/frames",
                "appearances": (f"/api/v1/live/sessions/{parent.session_id}/appearances"),
                "recordings": f"/api/v1/live/sessions/{parent.session_id}/recordings",
            },
            "outputs": {
                "recording": {
                    "state": self._output_state(recording_enabled, state),
                    "urls": {},
                },
                "annotated_stream": {
                    "state": self._output_state(annotated_enabled, state),
                    "urls": {},
                },
            },
        }

    @staticmethod
    def _public_state(generation: Any) -> str:
        if generation.runtime_state in {
            "STARTING",
            "ACTIVE",
            "RECONNECTING",
            "STOPPING",
            "STOPPED",
            "FAILED",
        }:
            return str(generation.runtime_state)
        if generation.desired_state == "stopped":
            return "STOPPING"
        if generation.media_state == "failed":
            return "FAILED"
        if generation.media_state == "ready":
            return "STARTING"
        if generation.media_state == "waiting":
            return "WAITING_FOR_SOURCE"
        return "ACCEPTED"

    @staticmethod
    def _output_state(enabled: bool, session_state: str) -> str:
        if not enabled:
            return "disabled"
        if session_state == "WAITING_FOR_SOURCE":
            return "waitingForSource"
        if session_state in {"STOPPING", "STOPPED", "FAILED"}:
            return "unavailable"
        return "pending"

    @staticmethod
    def _location_snapshot(request: LiveSessionCreateRequest) -> dict[str, Any] | None:
        if request.location is None:
            return None
        return request.location.model_dump(by_alias=True, exclude_none=True)

    @staticmethod
    def _safe_request_snapshot(
        request: LiveSessionCreateRequest | LiveSessionReconfigureRequest,
    ) -> dict[str, Any]:
        snapshot = request.model_dump(mode="json", by_alias=True)
        snapshot["source"] = {"type": request.source.type}
        return snapshot

    @staticmethod
    def _not_found() -> LiveSessionError:
        return LiveSessionError("Live session not found", "LIVE_SESSION_NOT_FOUND", 404)
