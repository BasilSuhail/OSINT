"""Full-text index over event title and summary (#779).

Search has to answer while the reader is still typing. Measured on the live
table before this index, a single `plainto_tsquery` over the seven-day
window took 394 ms — the planner walks the category index and recomputes
`to_tsvector` for every candidate row, because a functional predicate it
cannot look up is a predicate it must evaluate.

The expression is indexed rather than stored in a generated column: the
text lives inside the `payload` JSON, a generated column would duplicate
every headline on disk across 464k rows, and nothing else needs the vector
materialised.

CONCURRENTLY, because this table is written continuously by the fetchers
and a plain CREATE INDEX takes an ACCESS EXCLUSIVE lock for the whole
build. That forces autocommit — Alembic wraps migrations in a transaction
and CONCURRENTLY cannot run inside one.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Must match `app.search.SEARCH_VECTOR_SQL` exactly. Postgres only uses an
#: expression index when the query's expression is identical to the indexed
#: one — a different coalesce order, or 'simple' where this says 'english',
#: silently falls back to a sequential scan and the index is dead weight.
INDEX_NAME = "events_search_idx"
VECTOR_SQL = (
    "to_tsvector('english', "
    "coalesce(payload->>'title', '') || ' ' || coalesce(payload->>'summary', ''))"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            f"ON events USING GIN ({VECTOR_SQL})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
