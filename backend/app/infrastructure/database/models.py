from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.infrastructure.database.ids import new_uuid7


class FaceIdentity(Base):
    __tablename__ = "face_identity"

    face_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    samples: Mapped[list[FaceSample]] = relationship(back_populates="identity", lazy="raise")
    results: Mapped[list[RecognitionResult]] = relationship(back_populates="identity", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('anonymous', 'known')",
            name="face_identity_status_check",
        ),
        CheckConstraint(
            "lifecycle_status = 'known' OR (name IS NULL AND metadata = '{}'::jsonb)",
            name="face_identity_anonymous_pii_check",
        ),
        CheckConstraint(
            "lifecycle_status = 'anonymous' OR (name IS NOT NULL AND length(name) > 0)",
            name="face_identity_known_name_check",
        ),
        Index("ix_face_identity_status_active", "lifecycle_status", "is_active"),
        Index(
            "ix_face_identity_active_null_deleted",
            "deleted_at",
            postgresql_where="deleted_at IS NULL",
        ),
    )


class FaceSample(Base):
    __tablename__ = "face_sample"

    sample_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    face_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("face_identity.face_id"),
        nullable=False,
    )
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    alignment_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocess_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bounding_box: Mapped[dict] = mapped_column(JSONB, nullable=False)
    landmarks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    identity: Mapped[FaceIdentity] = relationship(back_populates="samples", lazy="raise")

    __table_args__ = (
        UniqueConstraint(
            "bucket",
            "object_key",
            name="uq_face_sample_bucket_object_key",
        ),
        CheckConstraint(
            "lifecycle_state IN ("
            "'pending', 'blob_ready', 'indexed', 'active', 'inactive', 'failed'"
            ")",
            name="face_sample_lifecycle_state_check",
        ),
        Index("ix_face_sample_face_id", "face_id"),
        Index(
            "ix_face_sample_active_lifecycle",
            "is_active",
            "lifecycle_state",
        ),
    )


class ProcessRecord(Base):
    __tablename__ = "process_record"

    process_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid7
    )
    process_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    face_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    results: Mapped[list[RecognitionResult]] = relationship(
        back_populates="process",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    events: Mapped[list[ProcessEvent]] = relationship(
        back_populates="process",
        lazy="raise",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "process_type IN ('recognize', 'enroll', 'update', 'delete', 'video_recognize')",
            name="process_record_type_check",
        ),
        CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'cancelled')",
            name="process_record_status_check",
        ),
        Index("ix_process_record_created_at", "created_at"),
        Index("ix_process_record_status", "status"),
    )


class RecognitionResult(Base):
    __tablename__ = "recognition_result"

    result_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    process_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("process_record.process_id", ondelete="CASCADE"),
        nullable=False,
    )
    detection_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    face_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("face_identity.face_id"),
        nullable=False,
    )
    status_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    bounding_box: Mapped[dict] = mapped_column(JSONB, nullable=False)
    detector_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_sample_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("face_sample.sample_id"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    process: Mapped[ProcessRecord] = relationship(back_populates="results", lazy="raise")
    identity: Mapped[FaceIdentity] = relationship(back_populates="results", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "status_snapshot IN ('known', 'anonymous', 'new_anonymous')",
            name="recognition_result_status_snapshot_check",
        ),
        UniqueConstraint(
            "process_id",
            "detection_ordinal",
            name="uq_recognition_result_process_ordinal",
        ),
        Index("ix_recognition_result_process_id", "process_id"),
        Index("ix_recognition_result_face_id", "face_id"),
    )


class ProcessEvent(Base):
    __tablename__ = "process_event"

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    process_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("process_record.process_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sanitized_details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    process: Mapped[ProcessRecord] = relationship(back_populates="events", lazy="raise")

    __table_args__ = (
        Index("ix_process_event_process_id", "process_id"),
        Index("ix_process_event_event_type", "event_type"),
        Index("ix_process_event_created_at", "created_at"),
    )


class VideoJob(Base):
    __tablename__ = "video_job"

    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    process_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("process_record.process_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    source_object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    source_content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_retention_until: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    container_format: Mapped[str] = mapped_column(String(32), nullable=False)
    video_codec: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    fps: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    total_frames: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processed_frames: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    person_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sampling: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    tracks: Mapped[list[VideoTrack]] = relationship(
        back_populates="job", lazy="raise", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'cancelling', 'cancelled', 'completed', 'failed')",
            name="video_job_status_check",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="video_job_progress_check",
        ),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="video_job_attempt_check"),
        Index("ix_video_job_queue", "status", "available_at", "created_at"),
        Index("ix_video_job_lease", "status", "lease_expires_at"),
        Index("ix_video_job_retention", "source_retention_until", "source_deleted_at"),
    )


class VideoTrack(Base):
    __tablename__ = "video_track"

    track_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("video_job.job_id", ondelete="CASCADE"), nullable=False
    )
    track_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_tracker_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    face_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("face_identity.face_id"), nullable=False
    )
    recognition_result_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("recognition_result.result_id"), nullable=False
    )
    status_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    name_snapshot: Mapped[str | None] = mapped_column(String(255))
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    identity_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    first_frame: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_frame: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen: Mapped[float] = mapped_column(Float, nullable=False)
    total_duration: Mapped[float] = mapped_column(Float, nullable=False)
    detection_count: Mapped[int] = mapped_column(Integer, nullable=False)
    appearances: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    detections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    representative_sample_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("face_sample.sample_id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    job: Mapped[VideoJob] = relationship(back_populates="tracks", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "status_snapshot IN ('known', 'anonymous', 'new_anonymous')",
            name="video_track_status_check",
        ),
        UniqueConstraint("job_id", "track_ordinal", name="uq_video_track_job_ordinal"),
        Index("ix_video_track_job_id", "job_id"),
        Index("ix_video_track_face_id", "face_id"),
        Index("ix_video_track_face_seen", "face_id", "first_seen"),
    )


class LiveCamera(Base):
    __tablename__ = "live_camera"

    camera_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid7
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri_ciphertext: Mapped[str] = mapped_column(String(8192), nullable=False)
    uri_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(16), nullable=False, default="stopped")
    desired_traceparent: Mapped[str | None] = mapped_column(String(55))
    desired_tracestate: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "desired_state IN ('stopped', 'running')", name="live_camera_desired_state_check"
        ),
        Index(
            "uq_live_camera_active_name",
            "name",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "uq_live_camera_active_uri_fingerprint",
            "uri_fingerprint",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "uq_live_single_running",
            "desired_state",
            unique=True,
            postgresql_where="desired_state = 'running' AND deleted_at IS NULL",
        ),
        Index("ix_live_camera_active_created", "is_active", "created_at"),
    )


class LiveCameraRun(Base):
    __tablename__ = "live_camera_run"

    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid7)
    camera_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("live_camera.camera_id"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    runtime_state: Mapped[str] = mapped_column(String(16), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    traceparent: Mapped[str] = mapped_column(String(55), nullable=False)
    tracestate: Mapped[str | None] = mapped_column(String(512))
    first_frame_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_frame_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_path: Mapped[str | None] = mapped_column(String(512))
    error_code: Mapped[str | None] = mapped_column(String(64))
    sanitized_error: Mapped[str | None] = mapped_column(String(512))
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("generation > 0", name="live_camera_run_generation_check"),
        CheckConstraint("reconnect_count >= 0", name="live_camera_run_reconnect_count_check"),
        CheckConstraint(
            "runtime_state IN ('STARTING', 'ACTIVE', 'RECONNECTING', "
            "'STOPPING', 'STOPPED', 'FAILED')",
            name="live_camera_run_runtime_state_check",
        ),
        UniqueConstraint("camera_id", "generation", name="uq_live_run_camera_generation"),
        Index("ix_live_camera_run_camera_created", "camera_id", "created_at"),
        Index("ix_live_camera_run_lease", "runtime_state", "lease_expires_at"),
    )


class LiveDetectionEvent(Base):
    __tablename__ = "live_detection_event"

    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=new_uuid7
    )
    camera_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("live_camera.camera_id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("live_camera_run.run_id"), nullable=False
    )
    native_track_id: Mapped[int] = mapped_column(Numeric(20, 0), nullable=False)
    identity_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    face_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("face_identity.face_id")
    )
    name_snapshot: Mapped[str | None] = mapped_column(String(255))
    identity_version_snapshot: Mapped[int | None] = mapped_column(Integer)
    match_score: Mapped[float | None] = mapped_column(Float)
    nearest_known_score: Mapped[float | None] = mapped_column(Float)
    detector_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bounding_box: Mapped[dict] = mapped_column(JSONB, nullable=False)
    landmarks: Mapped[list] = mapped_column(JSONB, nullable=False)
    quality: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    snapshot_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    snapshot_bucket: Mapped[str | None] = mapped_column(String(128))
    snapshot_object_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('known', 'unknown')", name="live_detection_event_event_type_check"
        ),
        CheckConstraint(
            "snapshot_status IN ('pending', 'ready', 'failed', 'unavailable')",
            name="live_detection_event_snapshot_status_check",
        ),
        CheckConstraint(
            "native_track_id >= 0 AND native_track_id <= 18446744073709551615",
            name="live_detection_event_native_track_uint64_check",
        ),
        CheckConstraint(
            "(event_type = 'known' AND face_id IS NOT NULL AND name_snapshot IS NOT NULL) "
            "OR (event_type = 'unknown' AND face_id IS NULL AND name_snapshot IS NULL)",
            name="live_detection_event_identity_check",
        ),
        CheckConstraint(
            "(snapshot_bucket IS NULL) = (snapshot_object_key IS NULL)",
            name="live_detection_event_snapshot_pair_check",
        ),
        UniqueConstraint(
            "run_id",
            "native_track_id",
            "identity_epoch",
            "event_type",
            name="uq_live_event_run_track_epoch_type",
        ),
        Index("ix_live_event_camera_occurred", "camera_id", "occurred_at", "event_id"),
        Index("ix_live_event_face_occurred", "face_id", "occurred_at"),
    )
