"""Story reviews — nightly contradiction + cluster QA rows (WS-G step 3, #386).

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-10

Same guardrails as story_claims: one row per (story, method version), model +
prompt version pinned, no backfill, consumed by nothing until the annotator's
agreement rate is published.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_reviews",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("review", JSONB, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_reviews_unique"),
    )
    op.create_index("story_reviews_story_idx", "story_reviews", ["story_id"])


def downgrade() -> None:
    op.drop_index("story_reviews_story_idx", table_name="story_reviews")
    op.drop_table("story_reviews")
