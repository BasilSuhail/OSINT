"""Search reaches the whole table, not only the rows that ship prose (#938).

Measured on the live table over a thirty-day window, the index this replaces
covered 3.6% of the corpus — 80,901 of 2,251,447 rows. The vector was built
from `payload->>'title'` and `payload->>'summary'`, which only RSS reliably
carries, so every earthquake, fire detection, aircraft track and malware URL
on the map was invisible to the search box.

Two indexes, because the corpus splits in two:

**Rows with words.** GDELT puts its place in `geo_name` and its action in
`action_label`; USGS puts "10 km SW of…" in `place`; GDACS names its event in
`eventname` and `country_name`; abuse.ch classifies in `threat`. Adding those
to the vector is what makes a search for a place or a threat class find the
rows that mention it. Rows carrying none of them produce an empty tsvector,
and GIN stores no entry for one, so the 1.95M fire detections cost this index
nothing.

**Rows without.** A fire detection has no words and is not meant to — the
reading is the claim. Every row does carry `keywords`, drawn from a vocabulary
of 160 tokens over the same window, and that is what a topic search matches.
The array index is small because the vocabulary is.

CONCURRENTLY, because this table is written continuously by the fetchers and a
plain CREATE INDEX takes an ACCESS EXCLUSIVE lock for the whole build. That
forces autocommit — Alembic wraps migrations in a transaction and CONCURRENTLY
cannot run inside one. A concurrent build that fails leaves an INVALID index
behind rather than rolling back, so the drops use IF EXISTS and the creates are
idempotent: re-running after a failure is the recovery.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Must match `app.search.SEARCH_VECTOR_SQL` exactly. Postgres only uses an
#: expression index when the query's expression is identical to the indexed
#: one — a different coalesce order, or 'simple' where this says 'english',
#: silently falls back to a sequential scan and the index is dead weight.
#: `tests/test_search_index.py` compares the two strings so they cannot drift.
VECTOR_SQL = (
    "to_tsvector('english', "
    "coalesce(payload->>'title', '') || ' ' || "
    "coalesce(payload->>'summary', '') || ' ' || "
    "coalesce(payload->>'place', '') || ' ' || "
    "coalesce(payload->>'eventname', '') || ' ' || "
    "coalesce(payload->>'country_name', '') || ' ' || "
    "coalesce(payload->>'geo_name', '') || ' ' || "
    "coalesce(payload->>'action_label', '') || ' ' || "
    "coalesce(payload->>'threat', ''))"
)

VECTOR_INDEX = "events_search_v2_idx"
KEYWORDS_INDEX = "events_keywords_idx"

#: Superseded: its expression is a prefix of the new one, so every query that
#: used it now uses the wider index instead. Left in place it would be 20 MB
#: the writers maintain and no reader consults.
OLD_VECTOR_INDEX = "events_search_idx"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {VECTOR_INDEX} "
            f"ON events USING GIN ({VECTOR_SQL})"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {KEYWORDS_INDEX} "
            f"ON events USING GIN (keywords)"
        )
        #: Dropped last. Until the replacement is built and valid, it is the
        #: only thing standing between the reader and a sequential scan.
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {OLD_VECTOR_INDEX}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    old_vector = (
        "to_tsvector('english', "
        "coalesce(payload->>'title', '') || ' ' || coalesce(payload->>'summary', ''))"
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {OLD_VECTOR_INDEX} "
            f"ON events USING GIN ({old_vector})"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {VECTOR_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {KEYWORDS_INDEX}")
