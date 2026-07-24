"""Persist the composite's monthly signal history (#586).

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-24

The composite z-scores each country against its own past and needs three prior
monthly observations before it emits anything but the neutral 0.5. It rebuilt
that past from the events table on every run, but retention keeps ~30 days: 183
of 184 countries had one or two monthly observations, so every live score was
exactly 0.5.

One row per (country, month, domain) — a few thousand a year — so the analysis
history no longer dies with the events it was derived from. Housekeeping does
not touch this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "composite_signals",
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("country", "bucket_start", "domain"),
    )
    op.create_index("composite_signals_bucket_idx", "composite_signals", ["bucket_start"])


def downgrade() -> None:
    op.drop_index("composite_signals_bucket_idx", table_name="composite_signals")
    op.drop_table("composite_signals")
