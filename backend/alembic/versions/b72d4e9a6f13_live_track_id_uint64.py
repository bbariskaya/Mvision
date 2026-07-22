"""store live native track IDs as uint64

Revision ID: b72d4e9a6f13
Revises: a81f5c2d9e40
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b72d4e9a6f13"
down_revision: str | Sequence[str] | None = "a81f5c2d9e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "live_detection_event",
        "native_track_id",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(20, 0),
        existing_nullable=False,
        postgresql_using="native_track_id::numeric(20, 0)",
    )
    op.create_check_constraint(
        "live_detection_event_native_track_uint64_check",
        "live_detection_event",
        "native_track_id >= 0 AND native_track_id <= 18446744073709551615",
    )


def downgrade() -> None:
    op.drop_constraint(
        "live_detection_event_native_track_uint64_check",
        "live_detection_event",
        type_="check",
    )
    op.alter_column(
        "live_detection_event",
        "native_track_id",
        existing_type=sa.Numeric(20, 0),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="native_track_id::bigint",
    )
