"""phase2 video backend

Revision ID: c21d7a1e4f02
Revises: 58ecca5e38a3
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c21d7a1e4f02"
down_revision: str | Sequence[str] | None = "58ecca5e38a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "process_record",
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("ck_process_record_process_record_type_check"),
        "process_record",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_process_record_process_record_status_check"),
        "process_record",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_process_record_process_record_type_check"),
        "process_record",
        "process_type IN ('recognize', 'enroll', 'update', 'delete', 'video_recognize')",
    )
    op.create_check_constraint(
        op.f("ck_process_record_process_record_status_check"),
        "process_record",
        "status IN ('started', 'completed', 'failed', 'cancelled')",
    )

    op.create_table(
        "video_job",
        sa.Column("job_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("process_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("source_bucket", sa.String(length=128), nullable=False),
        sa.Column("source_object_key", sa.String(length=512), nullable=False),
        sa.Column("source_content_type", sa.String(length=128), nullable=False),
        sa.Column("source_size", sa.BigInteger(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("container_format", sa.String(length=32), nullable=False),
        sa.Column("video_codec", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("total_frames", sa.BigInteger(), nullable=False),
        sa.Column("processed_frames", sa.BigInteger(), nullable=False),
        sa.Column("person_count", sa.Integer(), nullable=False),
        sa.Column("sampling", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name=op.f("ck_video_job_video_job_attempt_check"),
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name=op.f("ck_video_job_video_job_progress_check"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'cancelling', 'cancelled', 'completed', 'failed')",
            name=op.f("ck_video_job_video_job_status_check"),
        ),
        sa.ForeignKeyConstraint(["process_id"], ["process_record.process_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("process_id"),
        sa.UniqueConstraint("source_object_key"),
    )
    op.create_index("ix_video_job_queue", "video_job", ["status", "available_at", "created_at"])
    op.create_index("ix_video_job_lease", "video_job", ["status", "lease_expires_at"])
    op.create_index(
        "ix_video_job_retention", "video_job", ["source_retention_until", "source_deleted_at"]
    )

    op.create_table(
        "video_track",
        sa.Column("track_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("track_ordinal", sa.Integer(), nullable=False),
        sa.Column("source_tracker_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("face_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("recognition_result_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("status_snapshot", sa.String(length=16), nullable=False),
        sa.Column("name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("metadata_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("identity_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("threshold_used", sa.Float(), nullable=False),
        sa.Column("first_frame", sa.BigInteger(), nullable=False),
        sa.Column("last_frame", sa.BigInteger(), nullable=False),
        sa.Column("first_seen", sa.Float(), nullable=False),
        sa.Column("last_seen", sa.Float(), nullable=False),
        sa.Column("total_duration", sa.Float(), nullable=False),
        sa.Column("detection_count", sa.Integer(), nullable=False),
        sa.Column("appearances", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("representative_sample_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status_snapshot IN ('known', 'anonymous', 'new_anonymous')",
            name=op.f("ck_video_track_video_track_status_check"),
        ),
        sa.ForeignKeyConstraint(["face_id"], ["face_identity.face_id"]),
        sa.ForeignKeyConstraint(["job_id"], ["video_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recognition_result_id"], ["recognition_result.result_id"]),
        sa.ForeignKeyConstraint(["representative_sample_id"], ["face_sample.sample_id"]),
        sa.PrimaryKeyConstraint("track_id"),
        sa.UniqueConstraint("job_id", "track_ordinal", name="uq_video_track_job_ordinal"),
    )
    op.create_index("ix_video_track_job_id", "video_track", ["job_id"])
    op.create_index("ix_video_track_face_id", "video_track", ["face_id"])
    op.create_index("ix_video_track_face_seen", "video_track", ["face_id", "first_seen"])


def downgrade() -> None:
    op.drop_table("video_track")
    op.drop_table("video_job")
    op.drop_constraint(
        op.f("ck_process_record_process_record_type_check"),
        "process_record",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_process_record_process_record_status_check"),
        "process_record",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_process_record_process_record_type_check"),
        "process_record",
        "process_type IN ('recognize', 'enroll', 'update', 'delete')",
    )
    op.create_check_constraint(
        op.f("ck_process_record_process_record_status_check"),
        "process_record",
        "status IN ('started', 'completed', 'failed')",
    )
    op.drop_column("process_record", "details")
