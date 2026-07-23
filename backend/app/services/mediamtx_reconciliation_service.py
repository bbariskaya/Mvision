import asyncio
import datetime
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import SecretStr

from app.infrastructure.database.repositories.live_session_repository import (
    LiveSessionRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.media.mediamtx_client import (
    MediaMtxClient,
    MediaMtxError,
    ingress_config,
)


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class SecretCipher(Protocol):
    def decrypt_secret(self, ciphertext: str) -> SecretStr | str: ...


@dataclass(frozen=True)
class ReconciliationResult:
    added: int = 0
    replaced: int = 0
    deleted: int = 0
    ready: int = 0
    waiting: int = 0
    failed: int = 0


class MediaMtxReconciliationService:
    def __init__(
        self,
        media: MediaMtxClient,
        generations: LiveSessionRepository,
        cipher: SecretCipher | None,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
        owned_prefix: str = "ingress/",
        stale_grace_seconds: float = 30.0,
        clock: Callable[[], datetime.datetime] | None = None,
    ):
        self._media = media
        self._generations = generations
        self._cipher = cipher
        self._session_factory = session_factory
        self._owned_prefix = owned_prefix
        self._stale_grace = datetime.timedelta(seconds=stale_grace_seconds)
        self._clock = clock or (lambda: datetime.datetime.now(datetime.UTC))
        self._stale_since: dict[str, datetime.datetime] = {}
        self._lock = asyncio.Lock()

    async def reconcile(self) -> ReconciliationResult:
        async with self._lock:
            return await self._reconcile_once()

    async def _reconcile_once(self) -> ReconciliationResult:
        counts = {key: 0 for key in ReconciliationResult.__dataclass_fields__}
        async with self._session_factory() as session:
            generations = await self._generations.list_reconcilable(session)
            desired_names = {generation.ingress_path for generation in generations}
            for generation in generations:
                try:
                    source_url = self._source_url(generation.source_ciphertext)
                    desired = ingress_config(generation.source_type, source_url)
                    current = await self._media.get_config_path(generation.ingress_path)
                    if current is None:
                        await self._media.add_path(generation.ingress_path, desired)
                        counts["added"] += 1
                    elif self._normalized(current) != desired:
                        await self._media.replace_path(generation.ingress_path, desired)
                        counts["replaced"] += 1
                    active = await self._media.get_active_path(generation.ingress_path)
                    state = (
                        "ready"
                        if active is not None and active.get("online") is True
                        else "waiting"
                    )
                    counts[state] += 1
                    await self._generations.set_media_state(
                        session, generation.generation_id, state
                    )
                except (MediaMtxError, ValueError):
                    counts["failed"] += 1
                    await self._generations.set_media_state(
                        session,
                        generation.generation_id,
                        "failed",
                        "LIVE_MEDIA_PATH_FAILED",
                    )

            now = self._clock()
            try:
                configured = await self._media.list_config_paths()
            except MediaMtxError:
                await session.commit()
                return ReconciliationResult(**counts)
            configured_names = {
                item["name"]
                for item in configured
                if isinstance(item.get("name"), str) and item["name"].startswith(self._owned_prefix)
            }
            for name in configured_names - desired_names:
                first_seen = self._stale_since.setdefault(name, now)
                if now - first_seen >= self._stale_grace:
                    await self._media.delete_path(name)
                    self._stale_since.pop(name, None)
                    counts["deleted"] += 1
            for name in desired_names | (set(self._stale_since) - configured_names):
                self._stale_since.pop(name, None)
            await session.commit()
        return ReconciliationResult(**counts)

    @staticmethod
    def _normalized(config: dict[str, Any]) -> dict[str, Any]:
        values = {"source": config.get("source")}
        if config.get("source", "").startswith(("rtsp://", "rtsps://")):
            values["rtspTransport"] = config.get("rtspTransport")
        return values

    def _source_url(self, ciphertext: str | None) -> str | None:
        if ciphertext is None:
            return None
        if self._cipher is None:
            raise ValueError("LIVE_SECRET_CONFIGURATION_REQUIRED")
        value = self._cipher.decrypt_secret(ciphertext)
        return value.get_secret_value() if isinstance(value, SecretStr) else value
