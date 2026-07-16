"""Story embeddings — semantic ask retrieval vectors (#441).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_embeddings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column("vector", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("story_id", "method_version", name="story_embeddings_unique"),
    )
    op.create_index("story_embeddings_created_idx", "story_embeddings", ["created_at"])


def downgrade() -> None:
    op.drop_index("story_embeddings_created_idx", table_name="story_embeddings")
    op.drop_table("story_embeddings")
