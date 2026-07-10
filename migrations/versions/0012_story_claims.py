"""Story claims — local-LLM extracted claims per story (WS-G step 1, #378).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-10

One row per (story, method version); method version pins model + prompt so
every claim is attributable. No backfill — extraction starts with the first
nightly beat, and nothing downstream consumes these rows until the model's
agreement with a human-checked sample is published.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_claims",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("claims", JSONB, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_claims_unique"),
    )
    op.create_index("story_claims_story_idx", "story_claims", ["story_id"])


def downgrade() -> None:
    op.drop_index("story_claims_story_idx", table_name="story_claims")
    op.drop_table("story_claims")
