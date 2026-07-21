import math
from dataclasses import dataclass

from app.infrastructure.database.ids import new_uuid7
from app.infrastructure.video.protocol import VideoDetection, VideoTrackOutput


@dataclass(frozen=True)
class SourceTrackTemplate:
    embedding: tuple[float, ...]
    detection_count: int
    best_confidence: float


@dataclass(frozen=True)
class CanonicalVideoTrack:
    track_id: str
    source_tracker_ids: tuple[int, ...]
    embedding: tuple[float, ...]
    representative_jpeg: bytes
    detections: tuple[VideoDetection, ...]
    appearances: tuple[dict, ...]
    first_seen: float
    last_seen: float
    total_duration: float
    source_templates: tuple[SourceTrackTemplate, ...] = ()


@dataclass
class _WorkingTrack:
    track_id: str
    source_tracker_ids: list[int]
    source_embeddings: list[tuple[float, ...]]
    source_templates: list[SourceTrackTemplate]
    embedding: tuple[float, ...]
    representative_jpeg: bytes
    representative_score: float
    detections: list[VideoDetection]


class VideoTrackingService:
    def __init__(
        self,
        reconciliation_threshold: float,
        appearance_max_gap_seconds: float,
    ):
        self._threshold = reconciliation_threshold
        self._max_gap = appearance_max_gap_seconds

    def reconcile(self, raw_tracks: list[VideoTrackOutput]) -> list[CanonicalVideoTrack]:
        working: list[_WorkingTrack] = []
        ordered = sorted(
            (track for track in raw_tracks if track.detections),
            key=lambda track: (track.detections[0].frame, track.tracker_id),
        )
        for raw in ordered:
            candidates = [
                (index, self._cosine(track.embedding, raw.embedding))
                for index, track in enumerate(working)
                if not self._overlaps(track.detections, raw.detections)
                and all(
                    self._cosine(source_embedding, raw.embedding) >= self._threshold
                    for source_embedding in track.source_embeddings
                )
            ]
            if not candidates:
                detections = sorted(raw.detections, key=lambda item: item.frame)
                working.append(
                    _WorkingTrack(
                        track_id=new_uuid7(),
                        source_tracker_ids=[raw.tracker_id],
                        source_embeddings=[raw.embedding],
                        source_templates=[self._source_template(raw)],
                        embedding=self._normalize(raw.embedding),
                        representative_jpeg=raw.representative_jpeg,
                        representative_score=max(
                            item.detector_confidence for item in detections
                        ),
                        detections=list(detections),
                    )
                )
                continue
            best_index = max(candidates, key=lambda item: item[1])[0]
            selected = working[best_index]
            selected.source_tracker_ids.append(raw.tracker_id)
            selected.source_embeddings.append(raw.embedding)
            selected.source_templates.append(self._source_template(raw))
            selected.embedding = self._normalize(
                tuple(left + right for left, right in zip(selected.embedding, raw.embedding))
            )
            selected.detections.extend(raw.detections)
            selected.detections.sort(key=lambda item: item.frame)
            score = max(item.detector_confidence for item in raw.detections)
            if raw.representative_jpeg and score > selected.representative_score:
                selected.representative_score = score
                selected.representative_jpeg = raw.representative_jpeg

        return [self._finalize(track) for track in working]

    def _finalize(self, track: _WorkingTrack) -> CanonicalVideoTrack:
        appearances: list[dict] = []
        start = track.detections[0]
        previous = start
        for detection in track.detections[1:]:
            if detection.timestamp - previous.timestamp > self._max_gap:
                appearances.append(self._appearance(start, previous))
                start = detection
            previous = detection
        appearances.append(self._appearance(start, previous))
        total_duration = round(
            sum(item["end"] - item["start"] for item in appearances), 6
        )
        return CanonicalVideoTrack(
            track_id=track.track_id,
            source_tracker_ids=tuple(track.source_tracker_ids),
            embedding=track.embedding,
            representative_jpeg=track.representative_jpeg,
            detections=tuple(track.detections),
            appearances=tuple(appearances),
            first_seen=track.detections[0].timestamp,
            last_seen=track.detections[-1].timestamp,
            total_duration=total_duration,
            source_templates=tuple(track.source_templates),
        )

    @staticmethod
    def _source_template(raw: VideoTrackOutput) -> SourceTrackTemplate:
        return SourceTrackTemplate(
            embedding=raw.embedding,
            detection_count=len(raw.detections),
            best_confidence=max(item.detector_confidence for item in raw.detections),
        )

    @staticmethod
    def _appearance(start: VideoDetection, end: VideoDetection) -> dict:
        return {
            "start": start.timestamp,
            "end": end.timestamp,
            "startFrame": start.frame,
            "endFrame": end.frame,
        }

    @staticmethod
    def _overlaps(
        left: list[VideoDetection], right: tuple[VideoDetection, ...]
    ) -> bool:
        return left[0].frame <= right[-1].frame and right[0].frame <= left[-1].frame

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True))

    @staticmethod
    def _normalize(values: tuple[float, ...]) -> tuple[float, ...]:
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 0 or not math.isfinite(norm):
            raise ValueError("Track embedding is not normalizable")
        return tuple(value / norm for value in values)
