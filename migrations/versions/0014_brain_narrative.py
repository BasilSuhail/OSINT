"""Brain situation narrative (#409).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brain_narrative",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("input_digest", sa.Text, nullable=False),
    )
    op.create_index("brain_narrative_created_idx", "brain_narrative", ["created_at"])


def downgrade() -> None:
    op.drop_index("brain_narrative_created_idx", table_name="brain_narrative")
    op.drop_table("brain_narrative")
