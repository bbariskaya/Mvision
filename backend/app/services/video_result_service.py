import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from app.config import Settings
from app.infrastructure.database.models import VideoJob, VideoTrack
from app.infrastructure.database.repositories import (
    ProcessRecordRepository,
    RecognitionResultRepository,
    VideoJobRepository,
    VideoTrackRepository,
)
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.video.protocol import VideoTrackOutput
from app.services.face_matcher import FaceMatch
from app.services.face_sample_persistence_service import FaceSamplePersistenceService
from app.services.video_identity_voting_service import (
    VideoIdentityDecision,
    VideoIdentityVotingService,
)
from app.services.video_tracking_service import CanonicalVideoTrack, VideoTrackingService


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[Any]: ...


EvidenceExtractor = Callable[[Path, float], Awaitable[bytes] | bytes]


class VideoFinalizationLeaseLostError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoFinalizationResult:
    person_count: int
    faces: tuple[dict[str, str], ...]


class VideoResultService:
    def __init__(
        self,
        settings: Settings,
        tracking: VideoTrackingService,
        voter: VideoIdentityVotingService,
        samples: FaceSamplePersistenceService,
        results: RecognitionResultRepository,
        tracks: VideoTrackRepository,
        jobs: VideoJobRepository,
        processes: ProcessRecordRepository,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
        evidence_extractor: EvidenceExtractor | None = None,
    ):
        self._settings = settings
        self._tracking = tracking
        self._voter = voter
        self._samples = samples
        self._results = results
        self._tracks = tracks
        self._jobs = jobs
        self._processes = processes
        self._session_factory = session_factory
        self._evidence_extractor = evidence_extractor or self._extract_frame

    async def finalize(
        self,
        job: VideoJob,
        raw_tracks: list[VideoTrackOutput],
        source_path: Path,
        worker_id: str,
        lease_token: str,
        processed_frames: int,
    ) -> VideoFinalizationResult:
        canonical_tracks = self._tracking.reconcile(raw_tracks)
        resolved_matches = [
            await self._voter.resolve(track) for track in canonical_tracks
        ]
        persisted: list[VideoTrack] = []
        faces: list[dict[str, str]] = []
        assigned: dict[str, list[tuple[float, float]]] = {}
        async with self._session_factory() as session:
            owned_job = await self._jobs.lock_owned(
                session, job.job_id, worker_id, lease_token, datetime.now(UTC)
            )
            if owned_job is None:
                raise VideoFinalizationLeaseLostError("Video job lease was lost")
            for ordinal, (track, decision) in enumerate(
                zip(canonical_tracks, resolved_matches, strict=True)
            ):
                match = decision.match
                if match is not None and self._blocked(match, track, assigned):
                    decision = VideoIdentityDecision(None, decision.score)
                outcome = await self._identity_outcome(
                    job, track, decision, source_path, ordinal
                )
                result_id = self._deterministic_id(job.job_id, track, ordinal, "result")
                track_id = self._deterministic_id(job.job_id, track, ordinal, "track")
                representative = max(
                    track.detections,
                    key=lambda item: (item.detector_confidence, -item.frame),
                )
                await self._results.create(
                    session,
                    result_id=result_id,
                    process_id=job.process_id,
                    detection_ordinal=ordinal,
                    face_id=outcome["face_id"],
                    status_snapshot=outcome["status"],
                    name_snapshot=outcome["name"],
                    metadata_snapshot=outcome["metadata"],
                    bounding_box=self._box(representative),
                    detector_confidence=representative.detector_confidence,
                    match_confidence=outcome["confidence"],
                    matched_sample_id=outcome["sample_id"],
                )
                persisted.append(
                    VideoTrack(
                        track_id=track_id,
                        job_id=job.job_id,
                        track_ordinal=ordinal,
                        source_tracker_ids=list(track.source_tracker_ids),
                        face_id=outcome["face_id"],
                        recognition_result_id=result_id,
                        status_snapshot=outcome["status"],
                        name_snapshot=outcome["name"],
                        metadata_snapshot=outcome["metadata"],
                        identity_version_snapshot=outcome["identity_version"],
                        match_confidence=outcome["confidence"],
                        threshold_used=outcome["threshold"],
                        first_frame=track.detections[0].frame,
                        last_frame=track.detections[-1].frame,
                        first_seen=track.first_seen,
                        last_seen=track.last_seen,
                        total_duration=track.total_duration,
                        detection_count=len(track.detections),
                        appearances=list(track.appearances),
                        detections=[self._detection(item) for item in track.detections],
                        representative_sample_id=outcome["sample_id"],
                    )
                )
                assigned.setdefault(outcome["face_id"], []).append(
                    (track.first_seen, track.last_seen)
                )
                faces.append(
                    {"face_id": outcome["face_id"], "status": outcome["status"]}
                )
            await self._tracks.replace_for_job(session, job.job_id, persisted)
            completed = await self._jobs.complete(
                session,
                job.job_id,
                worker_id,
                lease_token,
                len(persisted),
                processed_frames=processed_frames,
            )
            if not completed:
                raise VideoFinalizationLeaseLostError(
                    "Video job lease was lost before completion"
                )
            details = {
                "operation": "video_recognize",
                "video": {
                    "duration": job.duration_seconds,
                    "fps": job.fps,
                    "width": job.width,
                    "height": job.height,
                    "total_frames": job.total_frames,
                    "processed_frames": processed_frames,
                },
                "person_count": len(persisted),
                "faces": faces,
            }
            await self._processes.complete(
                session, job.process_id, len(persisted), details=details
            )
            await session.commit()
        return VideoFinalizationResult(len(persisted), tuple(faces))

    async def _identity_outcome(
        self,
        job: VideoJob,
        track: CanonicalVideoTrack,
        decision: VideoIdentityDecision,
        source_path: Path,
        ordinal: int,
    ) -> dict[str, Any]:
        match = decision.match
        if match is not None:
            known = match.identity.lifecycle_status == "known"
            return {
                "face_id": match.identity.face_id,
                "sample_id": match.sample_id,
                "status": "known" if known else "anonymous",
                "name": match.identity.name if known else None,
                "metadata": dict(match.identity.metadata_) if known else {},
                "identity_version": match.identity.version,
                "confidence": min(1.0, max(0.0, match.score)),
                "threshold": self._settings.recognition_threshold
                if known
                else self._settings.anonymous_threshold,
            }

        face_id = self._deterministic_id(job.job_id, track, ordinal, "face")
        sample_id = self._deterministic_id(job.job_id, track, ordinal, "sample")
        evidence = track.representative_jpeg
        if not evidence:
            extracted = self._evidence_extractor(source_path, track.first_seen)
            evidence = await extracted if inspect.isawaitable(extracted) else extracted
        representative = max(
            track.detections,
            key=lambda item: (item.detector_confidence, -item.frame),
        )
        await self._samples.persist(
            process_id=job.process_id,
            face_id=face_id,
            sample_id=sample_id,
            aligned_bytes=evidence,
            media_type="image/jpeg",
            vector=list(track.embedding),
            bounding_box=self._box(representative),
            quality={"detector_confidence": representative.detector_confidence},
            detector_version=self._settings.detector_version,
            embedding_model_version=self._settings.model_version,
            alignment_version=self._settings.alignment_version,
            preprocess_version=self._settings.preprocess_version,
            manage_process=False,
        )
        return {
            "face_id": face_id,
            "sample_id": sample_id,
            "status": "new_anonymous",
            "name": None,
            "metadata": {},
            "identity_version": 1,
            "confidence": decision.score if decision.score is not None else 0.0,
            "threshold": self._settings.anonymous_threshold,
        }

    @staticmethod
    def _deterministic_id(
        job_id: str,
        track: CanonicalVideoTrack,
        ordinal: int,
        kind: str,
    ) -> str:
        source_ids = ",".join(str(value) for value in track.source_tracker_ids)
        return str(uuid5(UUID(job_id), f"{kind}:{ordinal}:{source_ids}"))

    @staticmethod
    def _blocked(
        match: FaceMatch,
        track: CanonicalVideoTrack,
        assigned: dict[str, list[tuple[float, float]]],
    ) -> bool:
        return any(
            track.first_seen <= end and start <= track.last_seen
            for start, end in assigned.get(match.identity.face_id, [])
        )

    @staticmethod
    def _box(detection: Any) -> dict[str, float]:
        return {
            "x": detection.x,
            "y": detection.y,
            "width": detection.width,
            "height": detection.height,
        }

    @classmethod
    def _detection(cls, detection: Any) -> dict[str, Any]:
        return {
            "frame": detection.frame,
            "timestamp": detection.timestamp,
            "boundingBox": cls._box(detection),
            "confidence": detection.detector_confidence,
            "landmarks": [
                {"x": detection.landmarks[index], "y": detection.landmarks[index + 1]}
                for index in range(0, 10, 2)
            ],
        }

    @staticmethod
    async def _extract_frame(source_path: Path, timestamp: float) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0 or not stdout.startswith(b"\xff\xd8"):
            raise RuntimeError("Failed to extract representative video frame")
        return stdout
