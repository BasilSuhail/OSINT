"""Drop raw OpenSky ADS-B state rows, superseded by hourly rollups (#496).

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-19

The fetcher now emits one event per country per hour instead of one per
aircraft observation. The historic raw rows — ~10.2M of them, roughly 6.5 GB —
carry no ``country``, so no consumer could ever read them: ``daily_side_counts``
matches on country, and the dashboard never rendered the source.

Raw rows are told apart from rollups by ``lat``: a raw state vector always has
a position, an hourly country aggregate never does. That discriminator is what
keeps this migration from touching rows written by the new fetcher.

There is no backfill. Retention is 30 days, so rolled-up history rebuilds
within a month of normal ingestion.

**Back up before running.** This is one-way:

    pg_dump "$DATABASE_URL" --table=events \\
      --data-only --format=custom --file=backups/opensky-raw-YYYYMMDD.dump

Deletes in batches so the operation never takes a long table-wide lock on a
Pi-class box.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 50_000


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite is only used for unit tests, which never hold 10M rows; a
        # single statement is simpler than the batched CTE below.
        bind.execute(
            sa.text("DELETE FROM events WHERE source = 'opensky-adsb' AND lat IS NOT NULL")
        )
        return

    while True:
        result = bind.execute(
            sa.text(
                """
                WITH doomed AS (
                    SELECT id FROM events
                    WHERE source = 'opensky-adsb' AND lat IS NOT NULL
                    LIMIT :batch
                )
                DELETE FROM events USING doomed WHERE events.id = doomed.id
                """
            ),
            {"batch": _BATCH},
        )
        if result.rowcount is None or result.rowcount == 0:
            break

    # The table loses most of its rows; reclaim the space and refresh planner
    # statistics so the aggregate queries in #498 plan against reality.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("VACUUM ANALYZE events"))


def downgrade() -> None:
    # Raw ADS-B state vectors are not reconstructible from the rollups, and the
    # upstream endpoint only serves the present moment. Restore from the dump
    # named in this module's docstring instead.
    raise NotImplementedError(
        "0017 is one-way; restore raw opensky rows from the pre-migration pg_dump"
    )
