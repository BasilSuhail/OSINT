"""Measured database figures for the README and docs (#562).

Every number the README states about data volume comes from here. It exists
because the figures were once read from `pg_stat_user_tables.n_live_tup`, which
is an autovacuum *estimate*: it reported 18 rows in `predictions` against an
actual 582. Estimates are fine for query planning and useless for documentation.

    uv run python scripts/db_snapshot.py

Counts are exact `count(*)`. They move — retention prunes news, hazard and
GDELT events at ~30 days, and ingestion runs continuously — so anything quoted
from this belongs next to the date it was taken.
"""

from datetime import UTC, datetime

from sqlalchemy import text

from app.db import session_scope

DERIVED_TABLES = [
    "stories",
    "story_members",
    "story_embeddings",
    "story_gist",
    "story_claims",
    "story_corroboration",
    "story_disagreement",
    "scores",
    "predictions",
    "gdelt_daily_volume",
    "gdelt_archive_day",
]


def main() -> None:
    with session_scope() as session:
        print(f"# database snapshot — {datetime.now(UTC):%Y-%m-%d}\n")

        total = session.execute(text("select count(*) from events")).scalar_one()
        size = session.execute(
            text("select pg_size_pretty(pg_database_size(current_database()))")
        ).scalar_one()
        sources = session.execute(text("select count(distinct source) from events")).scalar_one()
        print(f"events        {total:>10,}   across {sources} sources, DB {size}\n")

        print("## events by source")
        rows = session.execute(
            text(
                """
                select source, count(*) n,
                       min(occurred_at)::date lo, max(occurred_at)::date hi
                from events group by 1 order by 2 desc limit 12
                """
            )
        ).all()
        for row in rows:
            print(f"  {row.source:<22} {row.n:>9,}   {row.lo} .. {row.hi}")

        print("\n## derived")
        for table in DERIVED_TABLES:
            count = session.execute(text(f"select count(*) from {table}")).scalar_one()
            print(f"  {table:<22} {count:>9,}")


if __name__ == "__main__":
    main()
