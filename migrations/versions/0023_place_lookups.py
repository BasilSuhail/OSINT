"""Cache verified named-place coordinates for RSS enrichment (#745).

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-02

Wikidata is a shared public service. Positive and negative results persist so
repeated headlines do not repeat external lookups, and every coordinate keeps
the identity and resolver version that justified it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "place_lookups",
        sa.Column("lookup_key", sa.String(length=64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("context_country", sa.String(length=2), nullable=False),
        sa.Column("context_city", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("precision", sa.Text(), nullable=False),
        sa.Column("wikidata_id", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolver_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('resolved', 'no_match', 'ambiguous')",
            name="place_lookups_status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'resolved' AND lat IS NOT NULL AND lon IS NOT NULL "
            "AND wikidata_id IS NOT NULL AND label IS NOT NULL) OR status != 'resolved'",
            name="place_lookups_resolved_complete",
        ),
        sa.PrimaryKeyConstraint("lookup_key"),
    )
    op.create_index("place_lookups_checked_idx", "place_lookups", ["checked_at"])


def downgrade() -> None:
    op.drop_index("place_lookups_checked_idx", table_name="place_lookups")
    op.drop_table("place_lookups")
