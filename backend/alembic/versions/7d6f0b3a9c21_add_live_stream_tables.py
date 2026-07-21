"""add live stream tables

Revision ID: 7d6f0b3a9c21
Revises: c21d7a1e4f02
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7d6f0b3a9c21"
down_revision: str | Sequence[str] | None = "c21d7a1e4f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_camera",
        sa.Column("camera_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("uri_ciphertext", sa.String(length=8192), nullable=False),
        sa.Column("uri_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "desired_state", sa.String(length=16), server_default="stopped", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "desired_state IN ('stopped', 'running')",
            name=op.f("ck_live_camera_desired_state_check"),
        ),
        sa.PrimaryKeyConstraint("camera_id"),
    )
    op.create_index(
        "uq_live_camera_active_name",
        "live_camera",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_live_camera_active_uri_fingerprint",
        "live_camera",
        ["uri_fingerprint"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_live_single_running",
        "live_camera",
        ["desired_state"],
        unique=True,
        postgresql_where=sa.text("desired_state = 'running' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_live_camera_active_created",
        "live_camera",
        ["is_active", "created_at"],
    )

    op.create_table(
        "live_camera_run",
        sa.Column("run_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("camera_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("runtime_state", sa.String(length=16), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_frame_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnect_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_path", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("sanitized_error", sa.String(length=512), nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "generation > 0", name=op.f("ck_live_camera_run_generation_check")
        ),
        sa.CheckConstraint(
            "reconnect_count >= 0",
            name=op.f("ck_live_camera_run_reconnect_count_check"),
        ),
        sa.CheckConstraint(
            "runtime_state IN ('STARTING', 'ACTIVE', 'RECONNECTING', "
            "'STOPPING', 'STOPPED', 'FAILED')",
            name=op.f("ck_live_camera_run_runtime_state_check"),
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["live_camera.camera_id"]),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("camera_id", "generation", name="uq_live_run_camera_generation"),
    )
    op.create_index(
        "ix_live_camera_run_camera_created",
        "live_camera_run",
        ["camera_id", "created_at"],
    )
    op.create_index(
        "ix_live_camera_run_lease",
        "live_camera_run",
        ["runtime_state", "lease_expires_at"],
    )

    op.create_table(
        "live_detection_event",
        sa.Column("event_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("camera_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("native_track_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("face_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("identity_version_snapshot", sa.Integer(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("nearest_known_score", sa.Float(), nullable=True),
        sa.Column("detector_confidence", sa.Float(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bounding_box", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("landmarks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "quality",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("snapshot_bucket", sa.String(length=128), nullable=True),
        sa.Column("snapshot_object_key", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('known', 'unknown')",
            name=op.f("ck_live_detection_event_event_type_check"),
        ),
        sa.CheckConstraint(
            "snapshot_status IN ('pending', 'ready', 'failed', 'unavailable')",
            name=op.f("ck_live_detection_event_snapshot_status_check"),
        ),
        sa.CheckConstraint(
            "(event_type = 'known' AND face_id IS NOT NULL AND name_snapshot IS NOT NULL) "
            "OR (event_type = 'unknown' AND face_id IS NULL AND name_snapshot IS NULL)",
            name=op.f("ck_live_detection_event_identity_check"),
        ),
        sa.CheckConstraint(
            "(snapshot_bucket IS NULL) = (snapshot_object_key IS NULL)",
            name=op.f("ck_live_detection_event_snapshot_pair_check"),
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["live_camera.camera_id"]),
        sa.ForeignKeyConstraint(["face_id"], ["face_identity.face_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["live_camera_run.run_id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "run_id",
            "native_track_id",
            "event_type",
            name="uq_live_event_run_track_type",
        ),
    )
    op.create_index(
        "ix_live_event_camera_occurred",
        "live_detection_event",
        ["camera_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_live_event_face_occurred",
        "live_detection_event",
        ["face_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("live_detection_event")
    op.drop_table("live_camera_run")
    op.drop_table("live_camera")
