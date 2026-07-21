from app.infrastructure.video.protocol import VideoDetection, VideoTrackOutput
from app.services.video_tracking_service import VideoTrackingService


def _embedding(index: int) -> tuple[float, ...]:
    values = [0.0] * 512
    values[index] = 1.0
    return tuple(values)


def _track(
    tracker_id: int,
    frames: list[tuple[int, float]],
    embedding_index: int = 0,
    embedding: tuple[float, ...] | None = None,
):
    return VideoTrackOutput(
        tracker_id=tracker_id,
        embedding=embedding or _embedding(embedding_index),
        representative_jpeg=b"jpeg",
        detections=tuple(
            VideoDetection(frame, timestamp, 1, 2, 3, 4, 0.9)
            for frame, timestamp in frames
        ),
    )


def test_non_overlapping_similar_tracklets_merge():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=1.5)

    tracks = service.reconcile(
        [_track(1, [(0, 0.0), (1, 0.1)]), _track(2, [(10, 1.0), (11, 1.1)])]
    )

    assert len(tracks) == 1
    assert tracks[0].source_tracker_ids == (1, 2)
    assert [item.frame for item in tracks[0].detections] == [0, 1, 10, 11]
    assert tracks[0].first_seen == 0.0
    assert tracks[0].last_seen == 1.1


def test_merged_track_retains_source_templates():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=1.5)

    track = service.reconcile(
        [_track(1, [(0, 0.0)]), _track(2, [(10, 1.0), (11, 1.1)])]
    )[0]

    assert [item.embedding for item in track.source_templates] == [_embedding(0), _embedding(0)]
    assert [item.detection_count for item in track.source_templates] == [1, 2]
    assert [item.best_confidence for item in track.source_templates] == [0.9, 0.9]


def test_overlapping_tracklets_never_merge_even_with_same_embedding():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=1.5)

    tracks = service.reconcile(
        [_track(1, [(0, 0.0), (10, 1.0)]), _track(2, [(5, 0.5), (11, 1.1)])]
    )

    assert len(tracks) == 2


def test_dissimilar_tracklets_do_not_merge():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=1.5)

    tracks = service.reconcile(
        [_track(1, [(0, 0.0)]), _track(2, [(10, 1.0)], embedding_index=1)]
    )

    assert len(tracks) == 2


def test_tracklet_must_match_every_member_of_canonical_track():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=1.5)
    first = (1.0, 0.0, 0.0)
    bridge = (0.9, 0.435889894, 0.0)
    different_person = (0.7, 0.619422481, 0.355409326)

    tracks = service.reconcile(
        [
            _track(1, [(0, 0.0)], embedding=first),
            _track(2, [(10, 1.0)], embedding=bridge),
            _track(3, [(20, 2.0)], embedding=different_person),
        ]
    )

    assert [track.source_tracker_ids for track in tracks] == [(1, 2), (3,)]


def test_large_detection_gap_creates_separate_appearances():
    service = VideoTrackingService(reconciliation_threshold=0.8, appearance_max_gap_seconds=0.5)

    track = service.reconcile(
        [_track(1, [(0, 0.0), (1, 0.1), (20, 2.0), (21, 2.1)])]
    )[0]

    assert track.appearances == (
        {"start": 0.0, "end": 0.1, "startFrame": 0, "endFrame": 1},
        {"start": 2.0, "end": 2.1, "startFrame": 20, "endFrame": 21},
    )
    assert track.total_duration == 0.2
