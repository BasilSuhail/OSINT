"""Stories — WS-A story clustering tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-03

One `stories` row per real-world story; `story_members` links news events to
their story (append-only — assignments are never revisited). outlet_count is
the number of distinct feeds telling the story, the direct input for the
WS-C corroboration score.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("outlet_count", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("stories_last_seen_idx", "stories", ["last_seen"])

    op.create_table(
        "story_members",
        sa.Column("event_id", sa.BigInteger, primary_key=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("story_members_story_idx", "story_members", ["story_id"])


def downgrade() -> None:
    op.drop_table("story_members")
    op.drop_table("stories")
