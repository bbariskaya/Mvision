import asyncio
import datetime
import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from opentelemetry.trace import Status, StatusCode

from app.config import Settings
from app.infrastructure.database.models import LiveDetectionEvent
from app.infrastructure.database.repositories import LiveEventRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.live.protocol import (
    IdentityAssignment,
    ProtocolHeader,
    TrackEvidenceEvent,
    TrackExpiredEvent,
)
from app.observability.telemetry import TelemetryRuntime
from app.services.live_identity_service import LiveIdentityDecision

logger = logging.getLogger(__name__)


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


class LiveSnapshotStorage(Protocol):
    async def upload_live_snapshot(
        self, object_key: str, data: bytes, event_id: str
    ) -> Any: ...

    async def delete_live_snapshot(self, object_key: str) -> None: ...


class LiveNotifier(Protocol):
    async def publish(self, event: LiveDetectionEvent) -> None: ...


class InMemoryLiveNotifier:
    def __init__(self, queue_capacity: int = 64):
        self._queue_capacity = queue_capacity
        self._subscribers: set[asyncio.Queue[LiveDetectionEvent]] = set()

    def subscribe(self) -> asyncio.Queue[LiveDetectionEvent]:
        queue: asyncio.Queue[LiveDetectionEvent] = asyncio.Queue(
            maxsize=self._queue_capacity
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[LiveDetectionEvent]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: LiveDetectionEvent) -> None:
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


class LiveEventService:
    def __init__(
        self,
        settings: Settings,
        events: LiveEventRepository,
        storage: LiveSnapshotStorage,
        notifier: LiveNotifier,
        *,
        telemetry: TelemetryRuntime | None = None,
        session_factory: SessionFactory = AsyncSessionLocal,
    ):
        self._settings = settings
        self._events = events
        self._storage = storage
        self._notifier = notifier
        self._telemetry = telemetry or TelemetryRuntime(enabled=False)
        self._session_factory = session_factory
        self._revisions: dict[tuple[str, int], int] = {}
        self._pending: dict[tuple[str, int], tuple[TrackEvidenceEvent, LiveIdentityDecision]] = {}
        self._known_cooldown: dict[tuple[str, str], int] = {}
        self.suppressed_count = 0

    async def accept_decision(
        self,
        camera_id: str,
        run_id: str,
        generation: int,
        evidence: TrackEvidenceEvent,
        decision: LiveIdentityDecision,
    ) -> tuple[IdentityAssignment, ...]:
        self._validate_context(camera_id, run_id, generation, evidence)
        if decision.transition == "none":
            if decision.match is None:
                self._pending[(run_id, evidence.tracker_id)] = (evidence, decision)
            return ()
        if decision.transition == "unknown":
            self._pending.pop((run_id, evidence.tracker_id), None)
            await self._persist(camera_id, run_id, evidence, decision, "unknown")
            return (self._assignment(evidence, decision, "unknown"),)
        if decision.match is None or decision.reference_embedding is None:
            self._pending[(run_id, evidence.tracker_id)] = (evidence, decision)
            return ()

        face_id = str(decision.match.identity.face_id)
        cooldown_key = (camera_id, face_id)
        previous = self._known_cooldown.get(cooldown_key)
        cooldown_ns = int(self._settings.live_known_cooldown_seconds * 1_000_000_000)
        if previous is not None and evidence.last_seen_ns - previous < cooldown_ns:
            self.suppressed_count += 1
        else:
            await self._persist(camera_id, run_id, evidence, decision, "known")
            self._known_cooldown[cooldown_key] = evidence.last_seen_ns
        commands = []
        if decision.reset_required:
            commands.append(self._assignment(evidence, decision, "unknown"))
        commands.append(self._assignment(evidence, decision, "known"))
        return tuple(commands)

    async def expire_track(
        self,
        camera_id: str,
        run_id: str,
        generation: int,
        event: TrackExpiredEvent,
    ) -> tuple[IdentityAssignment, ...]:
        self._validate_context(camera_id, run_id, generation, event)
        pending = self._pending.pop((run_id, event.tracker_id), None)
        if pending is None:
            return ()
        evidence, decision = pending
        dwell_ns = event.last_seen_ns - event.first_seen_ns
        if dwell_ns < int(self._settings.live_unknown_min_dwell_seconds * 1_000_000_000):
            return ()
        await self._persist(camera_id, run_id, evidence, decision, "unknown")
        return (self._assignment(evidence, decision, "unknown"),)

    async def _persist(
        self,
        camera_id: str,
        run_id: str,
        evidence: TrackEvidenceEvent,
        decision: LiveIdentityDecision,
        event_type: str,
    ) -> LiveDetectionEvent:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{run_id}:{evidence.tracker_id}:{event_type}:{decision.identity_epoch}",
            )
        )
        object_key = f"live/{camera_id}/{event_id}/aligned"
        snapshot_status = "ready"
        snapshot_bucket = None
        snapshot_object_key = None
        uploaded = False
        with self._telemetry.start_span(
            "live.snapshot.upload", {"dependency": "minio"}
        ) as snapshot_span:
            try:
                info = await self._storage.upload_live_snapshot(
                    object_key, evidence.representative_aligned_jpeg, event_id
                )
                snapshot_bucket = info.bucket
                snapshot_object_key = info.object_key
                uploaded = True
            except Exception:
                snapshot_status = "failed"
                snapshot_span.set_attribute("error_code", "SNAPSHOT_UPLOAD_FAILED")
                snapshot_span.set_status(
                    Status(StatusCode.ERROR, "SNAPSHOT_UPLOAD_FAILED")
                )

        best = max(evidence.observations, key=lambda item: item.quality_score)
        match = decision.match
        identity = match.identity if match is not None else None
        row = LiveDetectionEvent(
            event_id=event_id,
            camera_id=camera_id,
            run_id=run_id,
            native_track_id=evidence.tracker_id,
            identity_epoch=decision.identity_epoch,
            event_type=event_type,
            face_id=str(identity.face_id) if identity is not None else None,
            name_snapshot=str(identity.name) if identity is not None else None,
            identity_version_snapshot=(
                int(identity.version) if identity is not None else None
            ),
            match_score=match.score if match is not None else None,
            nearest_known_score=decision.nearest_known_score,
            detector_confidence=best.detector_confidence,
            first_seen_at=self._timestamp(evidence.first_seen_ns),
            last_seen_at=self._timestamp(evidence.last_seen_ns),
            occurred_at=self._timestamp(evidence.last_seen_ns),
            bounding_box={
                "x": best.bbox[0],
                "y": best.bbox[1],
                "width": best.bbox[2],
                "height": best.bbox[3],
            },
            landmarks=list(best.landmarks),
            quality={**decision.quality, "identity_epoch": decision.identity_epoch},
            snapshot_status=snapshot_status,
            snapshot_bucket=snapshot_bucket,
            snapshot_object_key=snapshot_object_key,
        )
        with self._telemetry.start_span(
            "live.event.commit", {"dependency": "postgres"}
        ) as commit_span:
            try:
                async with self._session_factory() as session:
                    persisted = await self._events.create_once(session, row)
                    await session.commit()
            except Exception:
                commit_span.set_attribute("error_code", "LIVE_EVENT_COMMIT_FAILED")
                commit_span.set_status(
                    Status(StatusCode.ERROR, "LIVE_EVENT_COMMIT_FAILED")
                )
                if uploaded:
                    try:
                        await self._storage.delete_live_snapshot(object_key)
                    except Exception:
                        pass
                    logger.error(
                        "Live event database failure cleaned snapshot event_id=%s",
                        event_id,
                    )
                raise
        with self._telemetry.start_span("live.notification.publish") as notification_span:
            try:
                await self._notifier.publish(persisted)
            except Exception:
                notification_span.set_attribute("error_code", "LIVE_NOTIFICATION_FAILED")
                notification_span.set_status(
                    Status(StatusCode.ERROR, "LIVE_NOTIFICATION_FAILED")
                )
        return persisted

    def _assignment(
        self,
        evidence: TrackEvidenceEvent,
        decision: LiveIdentityDecision,
        identity_state: Literal["known", "unknown"],
    ) -> IdentityAssignment:
        key = (evidence.header.run_id, evidence.tracker_id)
        revision = self._revisions.get(key, 0) + 1
        self._revisions[key] = revision
        match = decision.match if identity_state == "known" else None
        identity = match.identity if match is not None else None
        return IdentityAssignment(
            ProtocolHeader(
                evidence.header.protocol_version,
                "identity_assignment",
                evidence.header.camera_id,
                evidence.header.run_id,
                evidence.header.generation,
                evidence.header.sequence + revision,
                evidence.header.traceparent,
                evidence.header.tracestate,
            ),
            evidence.tracker_id,
            revision,
            decision.identity_epoch,
            identity_state,
            str(identity.name) if identity is not None else None,
            str(identity.face_id) if identity is not None else None,
            match.score if match is not None else None,
            (
                decision.quality["recognition_threshold"]
                if match is not None
                else None
            ),
            decision.reference_embedding if match is not None else None,
            evidence.evidence_revision,
        )

    @staticmethod
    def _timestamp(value_ns: int) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(value_ns / 1_000_000_000, datetime.UTC)

    @staticmethod
    def _validate_context(
        camera_id: str,
        run_id: str,
        generation: int,
        event: TrackEvidenceEvent | TrackExpiredEvent,
    ) -> None:
        if (
            event.header.camera_id != camera_id
            or event.header.run_id != run_id
            or event.header.generation != generation
        ):
            raise ValueError("STALE_LIVE_EVIDENCE")
