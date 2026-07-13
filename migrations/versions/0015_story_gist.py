"""Story gist + tags — the brain's light enrichment layer (#413).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_gist",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("gist", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("escalating", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_gist_unique"),
    )
    op.create_index("story_gist_created_idx", "story_gist", ["created_at"])


def downgrade() -> None:
    op.drop_index("story_gist_created_idx", table_name="story_gist")
    op.drop_table("story_gist")
