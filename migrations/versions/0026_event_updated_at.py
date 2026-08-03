"""Track durable event revisions for live enrichment delivery (#762).

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("events_updated_at_idx", "events", ["updated_at"])


def downgrade() -> None:
    op.drop_index("events_updated_at_idx", table_name="events")
    op.drop_column("events", "updated_at")
