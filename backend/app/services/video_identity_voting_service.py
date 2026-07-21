import logging
import math
from dataclasses import dataclass, field

from app.config import Settings
from app.services.face_matcher import FaceMatch, FaceMatcher
from app.services.video_tracking_service import CanonicalVideoTrack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoIdentityDecision:
    match: FaceMatch | None
    score: float | None


@dataclass
class _IdentitySupport:
    identity: object
    votes: int = 0
    weight: float = 0.0
    weighted_score: float = 0.0
    best_match: FaceMatch | None = None
    scores: list[float] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        return self.weighted_score / self.weight


class VideoIdentityVotingService:
    def __init__(self, settings: Settings, matcher: FaceMatcher):
        self._settings = settings
        self._matcher = matcher

    async def resolve(self, track: CanonicalVideoTrack) -> VideoIdentityDecision:
        support: dict[str, _IdentitySupport] = {}
        total_weight = 0.0
        nearest_known_score: float | None = None
        for template in track.source_templates:
            candidates = await self._matcher.candidates(
                list(template.embedding),
                minimum_score=0.0,
            )
            known_candidates = [
                candidate
                for candidate in candidates
                if getattr(candidate.identity, "lifecycle_status", None) == "known"
            ]
            if known_candidates:
                template_nearest = max(candidate.score for candidate in known_candidates)
                nearest_known_score = (
                    template_nearest
                    if nearest_known_score is None
                    else max(nearest_known_score, template_nearest)
                )
            best_by_identity: dict[str, FaceMatch] = {}
            for candidate in known_candidates:
                if candidate.score < self._settings.video_track_vote_candidate_floor:
                    continue
                face_id = str(candidate.identity.face_id)
                current = best_by_identity.get(face_id)
                if current is None or candidate.score > current.score:
                    best_by_identity[face_id] = candidate
            eligible = list(best_by_identity.values())
            if not eligible:
                continue
            weight = 1.0 + math.log1p(template.detection_count)
            for candidate in eligible:
                item = support.setdefault(
                    str(candidate.identity.face_id), _IdentitySupport(candidate.identity)
                )
                item.votes += 1
                item.weight += weight
                item.weighted_score += candidate.score * weight
                item.scores.append(candidate.score)
                if item.best_match is None or candidate.score > item.best_match.score:
                    item.best_match = candidate
            total_weight += weight

        if not support:
            return VideoIdentityDecision(None, nearest_known_score)
        ranked = sorted(
            support.values(), key=lambda item: (item.mean_score, item.weight), reverse=True
        )
        winner = ranked[0]
        runner_score = ranked[1].mean_score if len(ranked) > 1 else 0.0
        logger.info(
            "video identity votes track=%s support=%s",
            track.track_id,
            [
                {
                    "face_id": str(item.identity.face_id),
                    "votes": item.votes,
                    "score": round(item.mean_score, 4),
                    "ratio": round(item.weight / total_weight, 4),
                }
                for item in ranked[:5]
            ],
        )
        if max(winner.scores) < self._settings.recognition_threshold:
            return VideoIdentityDecision(None, nearest_known_score)
        if winner.mean_score - runner_score < self._settings.video_track_vote_min_margin:
            return VideoIdentityDecision(None, winner.mean_score)
        assert winner.best_match is not None
        score = min(1.0, max(0.0, winner.mean_score))
        return VideoIdentityDecision(
            FaceMatch(winner.identity, winner.best_match.sample_id, score),
            score,
        )
