"""add durable live sessions, generations, runs, and connectors

Revision ID: d92a7f4c1b30
Revises: c83f19d4a2e7
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d92a7f4c1b30"
down_revision: str | Sequence[str] | None = "c83f19d4a2e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_session",
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("camera_external_id", sa.String(length=255), nullable=False),
        sa.Column("location_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "desired_state", sa.String(length=16), nullable=False, server_default="running"
        ),
        sa.Column(
            "current_generation", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "desired_state IN ('running', 'stopped')",
            name="live_session_desired_state_check",
        ),
        sa.CheckConstraint(
            "current_generation >= 1", name="live_session_generation_check"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_live_session_desired_updated",
        "live_session",
        ["desired_state", "updated_at"],
    )

    op.create_table(
        "live_connector",
        sa.Column("connector_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("connector_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("safe_config", postgresql.JSONB(), nullable=False),
        sa.Column("secret_ciphertext", sa.String(length=8192), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "connector_type IN ('webhook', 'kafka')", name="live_connector_type_check"
        ),
        sa.PrimaryKeyConstraint("connector_id"),
        sa.UniqueConstraint("name", name="uq_live_connector_name"),
    )
    op.create_index(
        "ix_live_connector_enabled_created",
        "live_connector",
        ["enabled", "created_at"],
    )

    op.create_table(
        "live_session_generation",
        sa.Column("generation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("requested_spec", postgresql.JSONB(), nullable=False),
        sa.Column("resolved_spec", postgresql.JSONB(), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_ciphertext", sa.String(length=8192), nullable=True),
        sa.Column("ingress_path", sa.String(length=255), nullable=False),
        sa.Column(
            "desired_state", sa.String(length=16), nullable=False, server_default="running"
        ),
        sa.Column(
            "runtime_state", sa.String(length=32), nullable=False, server_default="ACCEPTED"
        ),
        sa.Column(
            "media_state", sa.String(length=16), nullable=False, server_default="provisioning"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("generation >= 1", name="live_generation_number_check"),
        sa.CheckConstraint(
            "profile_version >= 1", name="live_generation_profile_version_check"
        ),
        sa.CheckConstraint(
            "source_type IN ('rtspPull', 'whepPull', 'whipPush')",
            name="live_generation_source_type_check",
        ),
        sa.CheckConstraint(
            "(source_type = 'whipPush' AND source_ciphertext IS NULL) OR "
            "(source_type IN ('rtspPull', 'whepPull') AND source_ciphertext IS NOT NULL)",
            name="live_generation_source_secret_check",
        ),
        sa.CheckConstraint(
            "desired_state IN ('running', 'stopped')",
            name="live_generation_desired_state_check",
        ),
        sa.CheckConstraint(
            "runtime_state IN ('ACCEPTED', 'WAITING_FOR_SOURCE', 'STARTING', "
            "'ACTIVE', 'RECONNECTING', 'STOPPING', 'STOPPED', 'FAILED')",
            name="live_generation_runtime_state_check",
        ),
        sa.CheckConstraint(
            "media_state IN ('provisioning', 'waiting', 'ready', 'failed')",
            name="live_generation_media_state_check",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["live_session.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("generation_id"),
        sa.UniqueConstraint(
            "session_id", "generation", name="uq_live_generation_session_number"
        ),
        sa.UniqueConstraint("ingress_path", name="uq_live_session_generation_ingress_path"),
    )
    op.create_index(
        "ix_live_generation_claim",
        "live_session_generation",
        ["desired_state", "media_state", "created_at"],
    )
    op.create_index(
        "ix_live_generation_session_created",
        "live_session_generation",
        ["session_id", "created_at"],
    )

    op.create_table(
        "live_session_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("runtime_attempt", sa.Integer(), nullable=False),
        sa.Column("runtime_state", sa.String(length=32), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "runtime_attempt >= 1", name="live_session_run_attempt_check"
        ),
        sa.CheckConstraint(
            "runtime_state IN ('STARTING', 'ACTIVE', 'RECONNECTING', "
            "'STOPPING', 'STOPPED', 'FAILED')",
            name="live_session_run_runtime_state_check",
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["live_session_generation.generation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint(
            "generation_id", "runtime_attempt", name="uq_live_session_run_attempt"
        ),
    )
    op.create_index(
        "ix_live_session_run_lease",
        "live_session_run",
        ["runtime_state", "lease_expires_at"],
    )
    op.create_index(
        "ix_live_session_run_generation_created",
        "live_session_run",
        ["generation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_session_run_generation_created", table_name="live_session_run"
    )
    op.drop_index("ix_live_session_run_lease", table_name="live_session_run")
    op.drop_table("live_session_run")
    op.drop_index(
        "ix_live_generation_session_created", table_name="live_session_generation"
    )
    op.drop_index("ix_live_generation_claim", table_name="live_session_generation")
    op.drop_table("live_session_generation")
    op.drop_index("ix_live_connector_enabled_created", table_name="live_connector")
    op.drop_table("live_connector")
    op.drop_index("ix_live_session_desired_updated", table_name="live_session")
    op.drop_table("live_session")
