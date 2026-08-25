"""Export one database's history as a bundle another can merge in.

Written for moving a machine's collected history onto the board that replaced
it. The board keeps collecting throughout: this is a merge, not a restore, and
nothing the destination already holds is overwritten.

Streams each table out with server-side ``COPY ... TO STDOUT WITH CSV HEADER``
into a gzip file, so a 2-million-row table costs no more memory than a small
one. No ``pg_dump``: a Homebrew client is routinely a major version behind the
server it is pointed at, and this needs neither the version match nor the
schema — the destination already has the schema.

What is left out, and why:

* ``alembic_version`` — the destination's own schema version is the true one.
  Copying this would tell it that it is on a version it is not.
* migration backup tables (``*_pre<issue>``) — snapshots of a column before a
  rewrite, meaningful only in the database that took them.
* operational logs — job runs, ingest health and failures, housekeeping runs.
  They record what one machine did, and reading them on another as though it
  did them is worse than not having them.
* Any source named with ``--exclude-source``. Satellite fire detections are
  ~90% of the rows here and nothing draws them, so they are the usual answer.

Usage:
    .venv/bin/python -m scripts.export_merge_bundle --out-dir bundle \\
        [--exclude-source nasa-firms] [--dry-run]

Output:
    <out-dir>/<table>.csv.gz     one per table, CSV with a header row
    <out-dir>/manifest.json      schema version, row counts, what was excluded

The manifest's schema version is what the loader checks before writing a row.
Merging across a schema change is the failure that produces a half-populated
table nobody notices until a query returns the wrong shape.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from app.settings import settings

#: Tables carrying history worth moving, ordered parents before children so a
#: partial run leaves the destination merge-able rather than half-linked.
BUNDLE_TABLES: tuple[str, ...] = (
    "events",
    "stories",
    "story_members",
    "story_sensor_checks",
    "story_corroboration",
    "story_disagreement",
    "story_claims",
    "story_reviews",
    "story_embeddings",
    "story_gist",
    "brain_narrative",
    "scores",
    "labels",
    "composite_signals",
    "predictions",
    "disagreement_pairs",
    "gdelt_daily_volume",
    "place_lookups",
)


def dsn() -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


def copy_statement(table: str, *, exclude_sources: list[str]) -> str:
    """``COPY`` for one table, filtered where filtering is meaningful.

    Only ``events`` has a ``source`` column to filter on. Its dependants are
    left whole: a story member pointing at an excluded event is dropped by the
    loader's own referential check rather than guessed at here, where the
    destination's contents are not known.
    """
    if table == "events" and exclude_sources:
        placeholders = ", ".join(f"'{s}'" for s in exclude_sources)
        return (
            f"COPY (SELECT * FROM {table} WHERE source NOT IN ({placeholders})) "
            "TO STDOUT WITH CSV HEADER"
        )
    return f"COPY (SELECT * FROM {table}) TO STDOUT WITH CSV HEADER"


def export_table(conn: psycopg.Connection, table: str, path: Path, *, statement: str) -> int:
    """Stream one table to a gzip file. Returns rows written.

    The count comes from the cursor rather than from counting newlines in the
    output: a story title may itself contain a newline, and inside a quoted CSV
    field that is data rather than a row boundary. Counted the naive way, the
    manifest overstated `stories` by fifteen.
    """
    with gzip.open(path, "wb") as fh, conn.cursor().copy(statement) as copy:
        for block in copy:
            fh.write(block)
        return copy.cursor.rowcount


def schema_version(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def run(out_dir: Path, *, exclude_sources: list[str], dry_run: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with psycopg.connect(dsn()) as conn:
        version = schema_version(conn)
        for table in BUNDLE_TABLES:
            statement = copy_statement(table, exclude_sources=exclude_sources)
            if dry_run:
                counted = statement.replace("TO STDOUT WITH CSV HEADER", "")
                counted = f"SELECT count(*) FROM ({counted.removeprefix('COPY ').strip()}) s"
                counts[table] = conn.execute(counted).fetchone()[0]
                continue
            counts[table] = export_table(
                conn, table, out_dir / f"{table}.csv.gz", statement=statement
            )
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": version,
        "excluded_sources": exclude_sources,
        "tables": counts,
        "total_rows": sum(counts.values()),
    }
    if not dry_run:
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        help="omit a source from `events` (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args()

    manifest = run(args.out_dir, exclude_sources=args.exclude_source, dry_run=args.dry_run)
    print(f"schema {manifest['schema_version']}  excluded {manifest['excluded_sources']}")
    for table, n in manifest["tables"].items():
        print(f"  {table:24} {n:>10,}")
    print(f"  {'TOTAL':24} {manifest['total_rows']:>10,}")


if __name__ == "__main__":
    main()
