"""Disagreement pairs — (country-pair, month) roll-up (WS-B step 3, #372).

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-09

Rebuilt idempotently from persisted story_disagreement rows on every
disagreement beat, so no backfill is needed here: the first beat after this
migration populates every month the story rows support.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "disagreement_pairs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("country_a", sa.String(2), nullable=False),
        sa.Column("country_b", sa.String(2), nullable=False),
        sa.Column("month", sa.Date, nullable=False),
        sa.Column("n_stories", sa.Integer, nullable=False),
        sa.Column("mean_divergence", sa.Float, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "country_a", "country_b", "month", "method_version", name="disagreement_pairs_unique"
        ),
        sa.CheckConstraint(
            "mean_divergence >= 0 AND mean_divergence <= 1", name="disagreement_pairs_range"
        ),
    )
    op.create_index("disagreement_pairs_month_idx", "disagreement_pairs", ["month"])


def downgrade() -> None:
    op.drop_index("disagreement_pairs_month_idx", table_name="disagreement_pairs")
    op.drop_table("disagreement_pairs")
