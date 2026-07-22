import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.config import Settings
from app.infrastructure.live.protocol import (
    LiveObservation,
    TrackEvidenceEvent,
    TrackExpiredEvent,
)
from app.services.face_matcher import FaceMatch
from app.services.video_identity_voting_service import VideoIdentityDecision
from app.services.video_tracking_service import CanonicalVideoTrack, SourceTrackTemplate

logger = logging.getLogger(__name__)


class IdentityVoter(Protocol):
    async def resolve(self, track: CanonicalVideoTrack) -> VideoIdentityDecision: ...


class ReferenceVectorStore(Protocol):
    async def get(self, sample_id: str) -> dict | None: ...


@dataclass(frozen=True)
class LiveIdentityDecision:
    identity_state: Literal["known", "pending", "unknown"]
    match: FaceMatch | None
    nearest_known_score: float | None
    identity_epoch: int
    reset_required: bool
    quality: dict[str, float]
    reference_embedding: tuple[float, ...] | None = None
    transition: Literal["none", "known", "unknown"] = "none"
    evaluation_sequence: int = 0


@dataclass
class _TrackIdentity:
    identity_epoch: int = 1
    seen_timestamps: set[int] = field(default_factory=set)
    observations: list[LiveObservation] = field(default_factory=list)
    discontinuous: list[LiveObservation] = field(default_factory=list)
    known_match: FaceMatch | None = None
    nearest_known_score: float | None = None
    reference_embedding: tuple[float, ...] | None = None
    candidate_face_id: str | None = None
    candidate_wins: int = 0
    rejected_windows: int = 0
    evaluation_sequence: int = 0


class LiveIdentityService:
    def __init__(
        self,
        settings: Settings,
        voter: IdentityVoter,
        vector_store: ReferenceVectorStore,
    ):
        self._settings = settings
        self._voter = voter
        self._vector_store = vector_store
        self._tracks: dict[tuple[str, str, int, int], _TrackIdentity] = {}

    async def resolve(self, event: TrackEvidenceEvent) -> LiveIdentityDecision:
        key = (
            event.header.camera_id,
            event.header.run_id,
            event.header.generation,
            event.tracker_id,
        )
        state = self._tracks.setdefault(key, _TrackIdentity())
        self._accept_new_observations(state, event.observations)
        state.evaluation_sequence += 1
        quality = {
            "recognition_threshold": self._settings.recognition_threshold,
            "candidate_floor": self._settings.video_track_vote_candidate_floor,
            "top_2_margin": self._settings.video_track_vote_min_margin,
        }
        if not state.observations:
            return LiveIdentityDecision(
                "pending",
                None,
                None,
                state.identity_epoch,
                False,
                quality,
                evaluation_sequence=state.evaluation_sequence,
            )

        try:
            vote = await self._voter.resolve(self._canonical_track(event, state))
        except Exception:
            logger.warning("Live identity query failed", exc_info=True)
            return self._current_decision(state, quality)
        state.nearest_known_score = vote.score
        if vote.match is None:
            state.candidate_face_id = None
            state.candidate_wins = 0
            state.rejected_windows += 1
            if state.known_match is not None and state.rejected_windows >= 3:
                state.identity_epoch += 1
                state.known_match = None
                state.reference_embedding = None
                state.rejected_windows = 0
                return LiveIdentityDecision(
                    "unknown",
                    None,
                    vote.score,
                    state.identity_epoch,
                    True,
                    quality,
                    transition="unknown",
                    evaluation_sequence=state.evaluation_sequence,
                )
            return self._current_decision(state, quality)

        state.rejected_windows = 0
        face_id = str(vote.match.identity.face_id)
        if state.known_match is not None and str(state.known_match.identity.face_id) == face_id:
            state.candidate_face_id = None
            state.candidate_wins = 0
            return self._current_decision(state, quality)
        if state.known_match is not None:
            if state.candidate_face_id == face_id:
                state.candidate_wins += 1
            else:
                state.candidate_face_id = face_id
                state.candidate_wins = 1
            if state.candidate_wins < 3:
                return self._current_decision(state, quality)

        reference = await self._reference(vote.match.sample_id)
        if reference is None:
            return self._current_decision(state, quality)
        replacing = state.known_match is not None
        if replacing:
            state.identity_epoch += 1
        state.known_match = vote.match
        state.reference_embedding = reference
        state.candidate_face_id = None
        state.candidate_wins = 0
        return LiveIdentityDecision(
            "known",
            vote.match,
            vote.score,
            state.identity_epoch,
            replacing,
            quality,
            reference,
            "known",
            state.evaluation_sequence,
        )

    def expire(self, event: TrackEvidenceEvent | TrackExpiredEvent) -> None:
        self._tracks.pop(
            (
                event.header.camera_id,
                event.header.run_id,
                event.header.generation,
                event.tracker_id,
            ),
            None,
        )

    def _accept_new_observations(
        self,
        state: _TrackIdentity,
        observations: tuple[LiveObservation, ...],
    ) -> None:
        for observation in sorted(observations, key=lambda item: item.timestamp_ns):
            if observation.timestamp_ns in state.seen_timestamps:
                continue
            state.seen_timestamps.add(observation.timestamp_ns)
            state.observations.append(observation)
            if len(state.observations) > 5:
                state.observations.pop(0)

    def _current_decision(
        self, state: _TrackIdentity, quality: dict[str, float]
    ) -> LiveIdentityDecision:
        return LiveIdentityDecision(
            "known" if state.known_match is not None else "pending",
            state.known_match,
            state.nearest_known_score,
            state.identity_epoch,
            False,
            quality,
            state.reference_embedding,
            "none",
            state.evaluation_sequence,
        )

    async def _reference(self, sample_id: str) -> tuple[float, ...] | None:
        try:
            point = await self._vector_store.get(sample_id)
            values = None if point is None else point.get("vector")
            if not isinstance(values, (list, tuple)) or len(values) != 512:
                return None
            vector = tuple(float(value) for value in values)
            if not all(math.isfinite(value) for value in vector):
                return None
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0.0:
                return None
            normalized = tuple(value / norm for value in vector)
            if not 0.99 <= math.sqrt(sum(value * value for value in normalized)) <= 1.01:
                return None
            return normalized
        except Exception:
            logger.warning("Live identity reference retrieval failed", exc_info=True)
            return None

    @staticmethod
    def _canonical_track(
        event: TrackEvidenceEvent, state: _TrackIdentity
    ) -> CanonicalVideoTrack:
        centroid = LiveIdentityService._centroid(state.observations)
        return CanonicalVideoTrack(
            track_id=f"{event.header.run_id}:{event.tracker_id}:{state.identity_epoch}",
            source_tracker_ids=(event.tracker_id,),
            embedding=centroid,
            representative_jpeg=event.representative_aligned_jpeg,
            detections=(),
            appearances=(),
            first_seen=state.observations[0].timestamp_ns / 1_000_000_000,
            last_seen=state.observations[-1].timestamp_ns / 1_000_000_000,
            total_duration=(
                state.observations[-1].timestamp_ns
                - state.observations[0].timestamp_ns
            )
            / 1_000_000_000,
            source_templates=tuple(
                SourceTrackTemplate(
                    observation.embedding,
                    1,
                    observation.detector_confidence,
                )
                for observation in state.observations
            ),
        )

    @staticmethod
    def _centroid(observations: list[LiveObservation]) -> tuple[float, ...]:
        dimensions = len(observations[0].embedding)
        values = [0.0] * dimensions
        for observation in observations:
            for index, value in enumerate(observation.embedding):
                values[index] += value
        return LiveIdentityService._normalize(tuple(values))

    @staticmethod
    def _normalize(values: tuple[float, ...]) -> tuple[float, ...]:
        norm = math.sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values) if norm else values

    @staticmethod
    def _cosine(first: tuple[float, ...], second: tuple[float, ...]) -> float:
        if len(first) != len(second):
            return -1.0
        first_norm = math.sqrt(sum(value * value for value in first))
        second_norm = math.sqrt(sum(value * value for value in second))
        if first_norm == 0.0 or second_norm == 0.0:
            return -1.0
        return sum(left * right for left, right in zip(first, second, strict=True)) / (
            first_norm * second_norm
        )
