"""Backfill — drop feed-country from uncitied news rows.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-25

National-paper feeds (Dawn, Geo) republish world news. Until this change
``entry_to_event`` fell back to the feed's ``default_country`` when no city
matched, tagging Oscars / foreign-quake headlines ``country='PK'``. Those
rows polluted the country side panel (``useCountryEvents`` filters on
``country``). The write-time fix stops new rows; this backfills existing
ones.

A news row with a country but no pinned city was only ever country-tagged via
the removed fallback (local / world rows always carry ``payload.city``). So
nulling exactly those rows reproduces the new behaviour without touching
correctly-attributed news.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE events
        SET country = NULL
        WHERE category = 'news'
          AND country IS NOT NULL
          AND (payload->>'city') IS NULL
        """
    )


def downgrade() -> None:
    # Irreversible: the original (incorrect) feed-country is not recoverable
    # once dropped. No-op so the revision stays reversible at the schema level.
    pass
