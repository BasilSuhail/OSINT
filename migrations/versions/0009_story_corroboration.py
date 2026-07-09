"""Story corroboration — the fixed corroboration-v1.0 score (WS-C step 4, #363).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-09

One row per (story, method version), overwrite-in-place while the story is in
the clustering window. No backfill: scores are computed live by the beat task
from owner_count + sensor verdicts; stories that left the window before this
migration have no verdicts to fold in, and absence stays honest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_corroboration",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("components", JSONB, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_corroboration_unique"),
        sa.CheckConstraint("score >= 0 AND score < 1", name="story_corroboration_score_range"),
    )
    op.create_index("story_corroboration_story_idx", "story_corroboration", ["story_id"])


def downgrade() -> None:
    op.drop_index("story_corroboration_story_idx", table_name="story_corroboration")
    op.drop_table("story_corroboration")
