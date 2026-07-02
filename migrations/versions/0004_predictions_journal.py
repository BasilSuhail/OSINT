"""Predictions — WS-E forward prediction journal.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-03

Every forecast is logged with a server-stamped issued_at before the outcome is
known, then graded exactly once when its window matures. The unique forecast
key backs an ON CONFLICT DO NOTHING insert so re-running the composite can
never rewrite an already-issued prediction.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_months", sa.Integer, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("outcome", sa.Integer),
        sa.Column("graded_at", sa.DateTime(timezone=True)),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "source",
            "method_version",
            "country",
            "bucket_start",
            "horizon_months",
            name="predictions_forecast_key",
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name="predictions_score_range"),
    )
    op.create_index("predictions_ungraded_idx", "predictions", ["outcome", "bucket_start"])


def downgrade() -> None:
    op.drop_table("predictions")
