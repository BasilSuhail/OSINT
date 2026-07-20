"""Daily per-country GDELT archive volume + an ingest ledger (#555).

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-20

The gate's narrative side reads the DOC API, which reaches back about three
months. These two tables hold what the raw 15-minute export grid yields
instead: one count per country per day, and a record of which days were walked.

Counts, not rows. Raw GDELT events are pruned at ~30 days, so a multi-year raw
backfill would delete itself; an aggregate is small enough to keep permanently
and is deliberately left out of the retention policy.

The ledger exists so a country with no coverage on a day can be told apart from
a day nobody downloaded. Without it the gate cannot distinguish a quiet
narrative from a missing one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gdelt_daily_volume",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("events", sa.Integer(), nullable=False),
        sa.Column("mentions", sa.BigInteger(), nullable=False),
        sa.Column("method_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country", "day", "method_version", name="gdelt_daily_volume_unique"),
    )
    op.create_index(
        "gdelt_daily_volume_lookup_idx", "gdelt_daily_volume", ["country", "day"], unique=False
    )

    op.create_table(
        "gdelt_archive_day",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("files_ok", sa.Integer(), nullable=False),
        sa.Column("files_missing", sa.Integer(), nullable=False),
        sa.Column("method_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "method_version", name="gdelt_archive_day_unique"),
    )


def downgrade() -> None:
    op.drop_table("gdelt_archive_day")
    op.drop_index("gdelt_daily_volume_lookup_idx", table_name="gdelt_daily_volume")
    op.drop_table("gdelt_daily_volume")
