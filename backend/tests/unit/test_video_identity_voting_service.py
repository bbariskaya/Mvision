from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.face_matcher import FaceMatch
from app.services.video_identity_voting_service import VideoIdentityVotingService
from app.services.video_tracking_service import CanonicalVideoTrack, SourceTrackTemplate


def _identity(face_id: str):
    return SimpleNamespace(face_id=face_id, lifecycle_status="known")


def _anonymous(face_id: str):
    return SimpleNamespace(face_id=face_id, lifecycle_status="anonymous")


def _track(values: list[float]) -> CanonicalVideoTrack:
    return CanonicalVideoTrack(
        track_id="track",
        source_tracker_ids=tuple(range(len(values))),
        embedding=(1.0,),
        representative_jpeg=b"",
        detections=(),
        appearances=(),
        first_seen=0,
        last_seen=1,
        total_duration=1,
        source_templates=tuple(
            SourceTrackTemplate((value,), 4, 0.9) for value in values
        ),
    )


class _Matcher:
    def __init__(self, responses):
        self.responses = responses

    async def candidates(self, embedding, *, minimum_score):
        return [item for item in self.responses[embedding[0]] if item.score >= minimum_score]


@pytest.mark.asyncio
async def test_two_moderate_votes_resolve_identity():
    identity = _identity("face-a")
    matcher = _Matcher(
        {1.0: [FaceMatch(identity, "s1", 0.82)], 2.0: [FaceMatch(identity, "s2", 0.80)]}
    )
    voter = VideoIdentityVotingService(Settings(), matcher)

    decision = await voter.resolve(_track([1.0, 2.0]))

    assert decision.match is not None
    assert decision.match.identity.face_id == "face-a"
    assert decision.match.sample_id == "s1"
    assert decision.score == pytest.approx(0.81)


@pytest.mark.asyncio
async def test_one_strong_vote_resolves_identity():
    identity = _identity("face-a")
    voter = VideoIdentityVotingService(
        Settings(recognition_threshold=0.9),
        _Matcher({1.0: [FaceMatch(identity, "s1", 0.93)], 2.0: []}),
    )

    assert (await voter.resolve(_track([1.0, 2.0]))).match is not None


@pytest.mark.asyncio
async def test_one_candidate_at_threshold_is_accepted_without_consensus():
    identity = _identity("face-a")
    voter = VideoIdentityVotingService(
        Settings(
            recognition_threshold=0.6,
            video_track_vote_candidate_floor=0.6,
        ),
        _Matcher({1.0: [FaceMatch(identity, "s1", 0.60)], 2.0: []}),
    )

    assert (await voter.resolve(_track([1.0, 2.0]))).match is not None


@pytest.mark.asyncio
async def test_rejected_vote_preserves_nearest_cosine():
    identity = _identity("face-a")
    voter = VideoIdentityVotingService(
        Settings(recognition_threshold=0.9),
        _Matcher({1.0: [FaceMatch(identity, "s1", 0.82)]}),
    )

    decision = await voter.resolve(_track([1.0]))

    assert decision.match is None
    assert decision.score == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_anonymous_exact_match_cannot_suppress_named_candidate():
    known = _identity("known-face")
    anonymous = _anonymous("anonymous-face")
    voter = VideoIdentityVotingService(
        Settings(
            recognition_threshold=0.6,
            video_track_vote_candidate_floor=0.6,
        ),
        _Matcher(
            {
                1.0: [
                    FaceMatch(anonymous, "anonymous-sample", 1.0),
                    FaceMatch(known, "known-sample", 0.72),
                ]
            }
        ),
    )

    decision = await voter.resolve(_track([1.0]))

    assert decision.match is not None
    assert decision.match.identity.face_id == "known-face"
    assert decision.score == pytest.approx(0.72)


@pytest.mark.asyncio
async def test_ambiguous_consensus_is_rejected():
    first = _identity("face-a")
    second = _identity("face-b")
    voter = VideoIdentityVotingService(
        Settings(),
        _Matcher(
            {
                1.0: [FaceMatch(first, "a1", 0.82)],
                2.0: [FaceMatch(first, "a2", 0.81)],
                3.0: [FaceMatch(second, "b1", 0.80)],
                4.0: [FaceMatch(second, "b2", 0.79)],
            }
        ),
    )

    decision = await voter.resolve(_track([1.0, 2.0, 3.0, 4.0]))

    assert decision.match is None
    assert decision.score == pytest.approx(0.815)
