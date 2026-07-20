from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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
            "process_type IN ('recognize', 'enroll', 'update', 'delete')",
            name="process_record_type_check",
        ),
        CheckConstraint(
            "status IN ('started', 'completed', 'failed')",
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
