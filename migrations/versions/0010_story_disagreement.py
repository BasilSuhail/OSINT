"""Story disagreement — per-story cross-country divergence (WS-B step 2, #370).

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-09

One row per (story, method version), overwrite-in-place inside the clustering
window. Stories with fewer than two known-origin country groups get no row.
No backfill: member articles of past stories are retention-pruned, so
historical divergence is uncomputable — absence stays honest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_disagreement",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("divergence", sa.Float, nullable=False),
        sa.Column("components", JSONB, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_disagreement_unique"),
        sa.CheckConstraint("divergence >= 0 AND divergence <= 1", name="story_disagreement_range"),
    )
    op.create_index("story_disagreement_story_idx", "story_disagreement", ["story_id"])


def downgrade() -> None:
    op.drop_index("story_disagreement_story_idx", table_name="story_disagreement")
    op.drop_table("story_disagreement")
