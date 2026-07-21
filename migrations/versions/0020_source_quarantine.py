"""Quarantine feeds that cannot succeed (#567).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-21

One row per source being rested, deleted the moment it answers again — the
absence of a row is the healthy state, so nothing has to be un-set.

`ingest_failures` had reached 6,910 rows, much of it feeds that could never
have worked: one answered 403 on every attempt for a week, at six requests per
hourly tick.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_quarantine",
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source"),
    )
    op.create_index("source_quarantine_retry_idx", "source_quarantine", ["retry_after"])


def downgrade() -> None:
    op.drop_index("source_quarantine_retry_idx", table_name="source_quarantine")
    op.drop_table("source_quarantine")
