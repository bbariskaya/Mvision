from types import SimpleNamespace

import pytest

from app.config import Settings
from app.infrastructure.live.protocol import (
    LiveObservation,
    ProtocolHeader,
    TrackEvidenceEvent,
)
from app.services.face_matcher import FaceMatch
from app.services.live_identity_service import LiveIdentityService
from app.services.video_identity_voting_service import (
    VideoIdentityDecision,
    VideoIdentityVotingService,
)

CAMERA_ID = "019b0000-0000-7000-8000-000000000001"
RUN_ID = "019b0000-0000-7000-8000-000000000002"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _identity(face_id: str, lifecycle_status: str = "known"):
    return SimpleNamespace(
        face_id=face_id,
        name=face_id,
        lifecycle_status=lifecycle_status,
        version=1,
    )


def _observation(timestamp_ns: int, embedding: tuple[float, ...]) -> LiveObservation:
    return LiveObservation(
        timestamp_ns,
        (10.0, 20.0, 100.0, 120.0),
        0.91,
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
        (0.9, 0.9, 0.9, 0.9, 0.9),
        0.8,
        0,
        embedding,
    )


def _event(*embeddings: tuple[float, ...], revision: int = 1) -> TrackEvidenceEvent:
    observations = tuple(
        _observation((index + 1) * 1_000_000_000, embedding)
        for index, embedding in enumerate(embeddings)
    )
    return TrackEvidenceEvent(
        ProtocolHeader(
            2,
            "track_evidence",
            CAMERA_ID,
            CAMERA_ID,
            RUN_ID,
            1,
            1,
            revision,
            TRACEPARENT,
            None,
        ),
        42,
        revision,
        observations[0].timestamp_ns,
        observations[-1].timestamp_ns,
        observations,
        b"\xff\xd8\xff\xd9",
    )


class _Matcher:
    def __init__(self, responses):
        self.responses = responses

    async def candidates(self, embedding, *, minimum_score):
        return [
            item for item in self.responses.get(tuple(embedding), ()) if item.score >= minimum_score
        ]

    async def candidates_batch(self, embeddings, *, minimum_score):
        return [
            [
                item
                for item in self.responses.get(tuple(embedding), ())
                if item.score >= minimum_score
            ]
            for embedding in embeddings
        ]


class _Vectors:
    async def get(self, sample_id):
        return {"sample_id": sample_id, "vector": [1.0] + [0.0] * 511}


def _service(responses, **overrides) -> LiveIdentityService:
    settings = Settings(
        _env_file=None,
        recognition_threshold=overrides.get("recognition_threshold", 0.8),
        video_track_vote_candidate_floor=0.7,
        video_track_vote_min_margin=0.05,
        video_track_reconciliation_threshold=0.6,
    )
    voter = VideoIdentityVotingService(
        settings,
        _Matcher(responses),
        eligible_lifecycle_statuses=frozenset({"known"}),
    )
    return LiveIdentityService(settings, voter, _Vectors())


@pytest.mark.asyncio
async def test_one_strong_named_vote_is_known() -> None:
    face = _identity("face-a")
    embedding = (1.0, 0.0)

    decision = await _service({embedding: [FaceMatch(face, "sample-a", 0.91)]}).resolve(
        _event(embedding)
    )

    assert decision.identity_state == "known"
    assert decision.match is not None
    assert decision.match.identity.face_id == "face-a"
    assert decision.nearest_known_score == pytest.approx(0.91)
    assert decision.reference_embedding == (1.0,) + (0.0,) * 511


@pytest.mark.asyncio
async def test_two_moderate_consistent_votes_are_known() -> None:
    face = _identity("face-a")
    first = (1.0, 0.0)
    second = (0.98, 0.2)
    responses = {
        first: [FaceMatch(face, "sample-a", 0.84)],
        second: [FaceMatch(face, "sample-b", 0.82)],
    }

    decision = await _service(responses).resolve(_event(first, second))

    assert decision.identity_state == "known"
    assert decision.match is not None
    assert decision.match.identity.face_id == "face-a"


@pytest.mark.asyncio
async def test_below_threshold_or_ambiguous_winner_remains_pending() -> None:
    first = _identity("face-a")
    second = _identity("face-b")
    embedding = (1.0, 0.0)

    below = await _service({embedding: [FaceMatch(first, "sample-a", 0.79)]}).resolve(
        _event(embedding)
    )
    ambiguous = await _service(
        {
            embedding: [
                FaceMatch(first, "sample-a", 0.85),
                FaceMatch(second, "sample-b", 0.83),
            ]
        }
    ).resolve(_event(embedding))

    assert below.identity_state == "pending"
    assert below.nearest_known_score == pytest.approx(0.79)
    assert ambiguous.identity_state == "pending"
    assert ambiguous.nearest_known_score == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_anonymous_and_inactive_candidates_cannot_win() -> None:
    known = _identity("known")
    anonymous = _identity("anonymous", "anonymous")
    inactive = _identity("inactive", "inactive")
    embedding = (1.0, 0.0)

    decision = await _service(
        {
            embedding: [
                FaceMatch(anonymous, "anonymous-sample", 0.99),
                FaceMatch(inactive, "inactive-sample", 0.98),
                FaceMatch(known, "known-sample", 0.86),
            ]
        }
    ).resolve(_event(embedding))

    assert decision.match is not None
    assert decision.match.identity.face_id == "known"


class _SequencedVoter:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.tracks = []

    async def resolve(self, track):
        self.tracks.append(track)
        return next(self.decisions)


@pytest.mark.asyncio
async def test_different_identity_requires_three_consecutive_wins() -> None:
    first = FaceMatch(_identity("face-a"), "sample-a", 0.9)
    second = FaceMatch(_identity("face-b"), "sample-b", 0.95)
    voter = _SequencedVoter(
        [
            VideoIdentityDecision(first, 0.9),
            VideoIdentityDecision(second, 0.95),
            VideoIdentityDecision(second, 0.95),
            VideoIdentityDecision(second, 0.95),
        ]
    )
    service = LiveIdentityService(Settings(_env_file=None), voter, _Vectors())
    embedding = (1.0, 0.0)

    initial = await service.resolve(_event(embedding, revision=1))
    first_challenge = await service.resolve(_event(embedding, embedding, revision=2))
    second_challenge = await service.resolve(_event(embedding, embedding, revision=3))
    switched = await service.resolve(_event(embedding, embedding, revision=4))

    assert initial.match is not None
    assert first_challenge.match is not None
    assert first_challenge.match.identity.face_id == "face-a"
    assert second_challenge.match is not None
    assert second_challenge.match.identity.face_id == "face-a"
    assert switched.match is not None
    assert switched.match.identity.face_id == "face-b"
    assert switched.identity_epoch == 2
    assert switched.reset_required


@pytest.mark.asyncio
async def test_three_rejected_windows_reset_known_identity_to_unknown() -> None:
    known = FaceMatch(_identity("face-a"), "sample-a", 0.9)
    voter = _SequencedVoter(
        [
            VideoIdentityDecision(known, 0.9),
            VideoIdentityDecision(None, 0.2),
            VideoIdentityDecision(None, 0.2),
            VideoIdentityDecision(None, 0.2),
        ]
    )
    service = LiveIdentityService(
        Settings(_env_file=None, video_track_reconciliation_threshold=0.6),
        voter,
        _Vectors(),
    )
    first = (1.0, 0.0)
    other = (0.0, 1.0)

    initial = await service.resolve(_event(first, revision=1))
    one_change = await service.resolve(_event(first, other, revision=2))
    two_changes = await service.resolve(_event(first, other, other, revision=3))
    reset = await service.resolve(_event(first, other, other, other, revision=4))

    assert initial.identity_state == "known"
    assert one_change.match is not None
    assert one_change.match.identity.face_id == "face-a"
    assert two_changes.match is not None
    assert reset.identity_state == "unknown"
    assert reset.match is None
    assert reset.identity_epoch == 2
    assert reset.reset_required
    assert reset.transition == "unknown"
