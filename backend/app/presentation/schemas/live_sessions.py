from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import ConfigDict, Field, SecretStr, field_validator

from app.presentation.schemas.faces import ApiModel, to_camel

LiveLabelField = Literal["name", "status", "recognitionConfidence", "trackId"]


def _default_label_fields() -> list[LiveLabelField]:
    return ["name", "status", "recognitionConfidence"]


def _validate_source_url(value: SecretStr, allowed_schemes: frozenset[str]) -> SecretStr:
    raw = value.get_secret_value()
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise ValueError("LIVE_SOURCE_CREDENTIAL_INVALID")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("LIVE_SOURCE_CREDENTIAL_INVALID") from exc
    if parsed.scheme.lower() not in allowed_schemes or not hostname:
        raise ValueError("LIVE_SOURCE_CREDENTIAL_INVALID")
    return value


class StrictLiveApiModel(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class RtspPullSource(StrictLiveApiModel):
    type: Literal["rtspPull"]
    url: SecretStr

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: SecretStr) -> SecretStr:
        return _validate_source_url(value, frozenset({"rtsp", "rtsps"}))


class WhepPullSource(StrictLiveApiModel):
    type: Literal["whepPull"]
    url: SecretStr

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: SecretStr) -> SecretStr:
        return _validate_source_url(value, frozenset({"whep", "wheps"}))


class WhipPushSource(StrictLiveApiModel):
    type: Literal["whipPush"]


LiveSource = Annotated[
    RtspPullSource | WhepPullSource | WhipPushSource,
    Field(discriminator="type"),
]


class LiveLocation(StrictLiveApiModel):
    site: str | None = Field(default=None, max_length=128)
    area: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)


class LiveSampling(StrictLiveApiModel):
    mode: Literal["everyNFrames", "framesPerSecond"] = "everyNFrames"
    value: float = Field(default=1, gt=0)


class LiveProcessing(StrictLiveApiModel):
    mode: Literal["detect", "detectTrack", "recognize"] = "recognize"
    sampling: LiveSampling = Field(default_factory=LiveSampling)
    detector_threshold: float = Field(default=0.5, ge=0, le=1)
    recognition_threshold: float = Field(default=0.62, ge=0, le=1)
    anonymous_threshold: float = Field(default=0.7, ge=0, le=1)
    top2_margin: float = Field(default=0.05, ge=0, le=1)
    minimum_identity_evidence: int = Field(default=3, ge=1)
    track_gap_ms: int = Field(default=1500, gt=0)
    persistent_anonymous: bool = False


class LiveSourcePolicy(StrictLiveApiModel):
    latency_ms: int = Field(default=100, ge=0, le=5000)
    frame_timeout_ms: int = Field(default=5000, gt=0, le=120000)
    reconnect_interval_ms: int = Field(default=2000, gt=0, le=120000)
    reconnect_attempts: int = Field(default=-1, ge=-1)


class LiveAppearanceSummary(StrictLiveApiModel):
    enabled: bool = False


class LiveJsonOutput(StrictLiveApiModel):
    connector_refs: list[str] = Field(default_factory=list)
    persist_frames: bool = False
    frame_retention: str = "24h"
    appearance_summary: LiveAppearanceSummary = Field(default_factory=LiveAppearanceSummary)

    @field_validator("connector_refs")
    @classmethod
    def validate_connector_refs(cls, values: list[str]) -> list[str]:
        try:
            return [str(UUID(value)) for value in values]
        except (ValueError, AttributeError) as exc:
            raise ValueError("LIVE_CONNECTOR_REFERENCE_INVALID") from exc


class LiveRecordingOutput(StrictLiveApiModel):
    enabled: bool = False
    segment_duration: str = "15m"
    retention: str = "7d"


class LiveBoundingBoxOutput(StrictLiveApiModel):
    enabled: bool = True
    line_width: int = Field(default=3, ge=1, le=10)


class LiveLandmarkOutput(StrictLiveApiModel):
    enabled: bool = False


class LiveAnnotatedOutput(StrictLiveApiModel):
    enabled: bool = False
    bounding_box: LiveBoundingBoxOutput = Field(default_factory=LiveBoundingBoxOutput)
    landmarks: LiveLandmarkOutput = Field(default_factory=LiveLandmarkOutput)
    label_fields: list[LiveLabelField] = Field(default_factory=_default_label_fields)


class LiveSessionCreateRequest(StrictLiveApiModel):
    schema_version: Literal[1]
    camera_id: str = Field(min_length=1, max_length=255)
    location: LiveLocation | None = None
    profile: str = "face-recognition-v1"
    source: LiveSource
    processing: LiveProcessing = Field(default_factory=LiveProcessing)
    source_policy: LiveSourcePolicy = Field(default_factory=LiveSourcePolicy)
    json_output: LiveJsonOutput = Field(default_factory=LiveJsonOutput, alias="json")
    recording: LiveRecordingOutput = Field(default_factory=LiveRecordingOutput)
    annotated_stream: LiveAnnotatedOutput = Field(default_factory=LiveAnnotatedOutput)


class LiveSessionReconfigureRequest(StrictLiveApiModel):
    schema_version: Literal[1]
    profile: str = "face-recognition-v1"
    source: LiveSource
    processing: LiveProcessing = Field(default_factory=LiveProcessing)
    source_policy: LiveSourcePolicy = Field(default_factory=LiveSourcePolicy)
    json_output: LiveJsonOutput = Field(default_factory=LiveJsonOutput, alias="json")
    recording: LiveRecordingOutput = Field(default_factory=LiveRecordingOutput)
    annotated_stream: LiveAnnotatedOutput = Field(default_factory=LiveAnnotatedOutput)


class LiveProfileResponse(ApiModel):
    id: str
    version: int


class LiveIngestResponse(ApiModel):
    type: Literal["rtspPull", "whepPull", "whipPush"]
    publish_url: str | None = None


class LiveSessionLinks(ApiModel):
    frames: str
    appearances: str
    recordings: str


class LiveOutputState(ApiModel):
    state: str
    urls: dict[str, str] = Field(default_factory=dict)


class LiveSessionOutputs(ApiModel):
    recording: LiveOutputState
    annotated_stream: LiveOutputState


class LiveSessionResponse(ApiModel):
    session_id: str
    generation: int
    state: str
    camera_id: str
    location: LiveLocation | None = None
    profile: LiveProfileResponse
    ingest: LiveIngestResponse
    links: LiveSessionLinks
    outputs: LiveSessionOutputs


class LiveSessionListResponse(ApiModel):
    sessions: list[LiveSessionResponse]


class LiveCapabilitiesResponse(ApiModel):
    schema_versions: list[int]
    profiles: list[LiveProfileResponse]
    source_types: list[str]
    processing_modes: list[str]
    sampling_modes: list[str]
    connector_types: list[str]
    max_concurrent_sessions: int
