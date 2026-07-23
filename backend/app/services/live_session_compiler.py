import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from app.presentation.schemas.live_sessions import (
    LiveSessionCreateRequest,
    LiveSessionReconfigureRequest,
)


@dataclass(frozen=True)
class ResolvedProcessingSpec:
    mode: str
    sampling_mode: str
    sampling_value: float
    detector_threshold: float
    recognition_threshold: float
    anonymous_threshold: float
    top2_margin: float
    minimum_identity_evidence: int
    track_gap_ms: int
    persistent_anonymous: bool
    alignment: Literal["fivePoint"] = "fivePoint"


@dataclass(frozen=True)
class ResolvedSourcePolicy:
    latency_ms: int
    frame_timeout_ms: int
    reconnect_interval_ms: int
    reconnect_attempts: int


@dataclass(frozen=True)
class ResolvedJsonOutput:
    connector_refs: tuple[str, ...]
    persist_frames: bool
    frame_retention: str
    appearance_summary_enabled: bool


@dataclass(frozen=True)
class ResolvedRecordingOutput:
    enabled: bool
    segment_duration: str
    retention: str


@dataclass(frozen=True)
class ResolvedAnnotatedOutput:
    enabled: bool
    bounding_box_enabled: bool
    bounding_box_line_width: int
    landmarks_enabled: bool
    label_fields: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedLiveSessionSpec:
    schema_version: int
    profile_id: str
    profile_version: int
    source_type: str
    processing: ResolvedProcessingSpec
    source_policy: ResolvedSourcePolicy
    json: ResolvedJsonOutput
    recording: ResolvedRecordingOutput
    annotated_stream: ResolvedAnnotatedOutput
    spec_hash: str


class LiveSessionCompiler:
    def __init__(
        self,
        profile_id: str = "face-recognition-v1",
        profile_version: int = 1,
    ):
        self._profile_id = profile_id
        self._profile_version = profile_version

    def compile(
        self, request: LiveSessionCreateRequest | LiveSessionReconfigureRequest
    ) -> ResolvedLiveSessionSpec:
        if request.profile != self._profile_id:
            raise ValueError("LIVE_PROFILE_NOT_FOUND")
        if not request.json_output.connector_refs and not request.json_output.persist_frames:
            raise ValueError("LIVE_JSON_SINK_REQUIRED")
        if request.processing.mode != "recognize" and request.processing.persistent_anonymous:
            raise ValueError("LIVE_SESSION_SPEC_INVALID")

        processing = ResolvedProcessingSpec(
            mode=request.processing.mode,
            sampling_mode=request.processing.sampling.mode,
            sampling_value=request.processing.sampling.value,
            detector_threshold=request.processing.detector_threshold,
            recognition_threshold=request.processing.recognition_threshold,
            anonymous_threshold=request.processing.anonymous_threshold,
            top2_margin=request.processing.top2_margin,
            minimum_identity_evidence=request.processing.minimum_identity_evidence,
            track_gap_ms=request.processing.track_gap_ms,
            persistent_anonymous=request.processing.persistent_anonymous,
        )
        source_policy = ResolvedSourcePolicy(
            latency_ms=request.source_policy.latency_ms,
            frame_timeout_ms=request.source_policy.frame_timeout_ms,
            reconnect_interval_ms=request.source_policy.reconnect_interval_ms,
            reconnect_attempts=request.source_policy.reconnect_attempts,
        )
        json_output = ResolvedJsonOutput(
            connector_refs=tuple(request.json_output.connector_refs),
            persist_frames=request.json_output.persist_frames,
            frame_retention=request.json_output.frame_retention,
            appearance_summary_enabled=request.json_output.appearance_summary.enabled,
        )
        recording = ResolvedRecordingOutput(
            enabled=request.recording.enabled,
            segment_duration=request.recording.segment_duration,
            retention=request.recording.retention,
        )
        annotated = ResolvedAnnotatedOutput(
            enabled=request.annotated_stream.enabled,
            bounding_box_enabled=request.annotated_stream.bounding_box.enabled,
            bounding_box_line_width=request.annotated_stream.bounding_box.line_width,
            landmarks_enabled=request.annotated_stream.landmarks.enabled,
            label_fields=tuple(request.annotated_stream.label_fields),
        )
        canonical_values = {
            "schema_version": request.schema_version,
            "profile_id": request.profile,
            "profile_version": self._profile_version,
            "source_type": request.source.type,
            "processing": asdict(processing),
            "source_policy": asdict(source_policy),
            "json": asdict(json_output),
            "recording": asdict(recording),
            "annotated_stream": asdict(annotated),
        }
        canonical = json.dumps(canonical_values, sort_keys=True, separators=(",", ":"))
        return ResolvedLiveSessionSpec(
            schema_version=request.schema_version,
            profile_id=request.profile,
            profile_version=self._profile_version,
            source_type=request.source.type,
            processing=processing,
            source_policy=source_policy,
            json=json_output,
            recording=recording,
            annotated_stream=annotated,
            spec_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
