"""add live identity epoch

Revision ID: a81f5c2d9e40
Revises: 7d6f0b3a9c21
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a81f5c2d9e40"
down_revision: str | Sequence[str] | None = "7d6f0b3a9c21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_detection_event",
        sa.Column("identity_epoch", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_constraint(
        "uq_live_event_run_track_type", "live_detection_event", type_="unique"
    )
    op.create_unique_constraint(
        "uq_live_event_run_track_epoch_type",
        "live_detection_event",
        ["run_id", "native_track_id", "identity_epoch", "event_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_live_event_run_track_epoch_type", "live_detection_event", type_="unique"
    )
    op.create_unique_constraint(
        "uq_live_event_run_track_type",
        "live_detection_event",
        ["run_id", "native_track_id", "event_type"],
    )
    op.drop_column("live_detection_event", "identity_epoch")
