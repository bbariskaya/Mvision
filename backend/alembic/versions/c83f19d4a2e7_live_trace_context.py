"""persist live trace context across API and worker processes

Revision ID: c83f19d4a2e7
Revises: b72d4e9a6f13
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c83f19d4a2e7"
down_revision: str | Sequence[str] | None = "b72d4e9a6f13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_camera", sa.Column("desired_traceparent", sa.String(length=55), nullable=True)
    )
    op.add_column(
        "live_camera", sa.Column("desired_tracestate", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "live_camera_run", sa.Column("traceparent", sa.String(length=55), nullable=True)
    )
    op.add_column(
        "live_camera_run", sa.Column("tracestate", sa.String(length=512), nullable=True)
    )
    op.execute(
        "UPDATE live_camera_run SET traceparent = "
        "'00-' || md5(run_id::text) || '-' || "
        "substr(md5(run_id::text || '-span'), 1, 16) || '-01' "
        "WHERE traceparent IS NULL"
    )
    op.alter_column("live_camera_run", "traceparent", nullable=False)


def downgrade() -> None:
    op.drop_column("live_camera_run", "tracestate")
    op.drop_column("live_camera_run", "traceparent")
    op.drop_column("live_camera", "desired_tracestate")
    op.drop_column("live_camera", "desired_traceparent")
