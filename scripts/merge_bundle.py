"""Merge a bundle exported by `scripts.export_merge_bundle` into this database.

The destination keeps collecting throughout and nothing it already holds is
overwritten. Rows both machines saw are kept once; rows only the source has are
added underneath.

Three problems have to be solved for that to be true rather than merely
apparent, and each one fails silently if it is not:

**Colliding identifiers.** Every ``id`` sequence starts at 1 on both machines,
so the same number means a different row on each. Each table's ids are shifted
past the destination's highest before anything is inserted, which keeps the
bundle's own internal links consistent because every id in it moves together.

**Links that survive a conflict.** ``events`` dedups on its natural key, so an
event both machines saw is kept as the destination's row, with the
destination's id — not the shifted one. A ``story_members`` row pointing at the
shifted id would then point at nothing. Event references are therefore shifted
with everything else and then re-resolved through ``(source, source_event_id)``
after the insert, so they land on whichever row actually won. A reference that
resolves to nothing — its event was excluded from the bundle, or never
inserted — is dropped rather than carried, because a story citing an event that
is not there is worse than a story with one fewer source.

**A schema that has moved.** The bundle records the schema version it was taken
at, and this refuses to write a row unless the destination agrees. Merging
across a migration is how a table ends up half-populated in a shape nobody
notices until a query returns the wrong thing.

Everything runs in one transaction. A failure leaves the database exactly as it
was, and the staging schema is dropped either way.

Usage:
    python -m scripts.merge_bundle --bundle-dir /data/bundle [--dry-run]
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import psycopg

from app.settings import settings

#: Columns that reference `stories.id`, shifted with the stories they name.
STORY_REFS: dict[str, tuple[str, ...]] = {
    "story_members": ("story_id",),
    "story_sensor_checks": ("story_id",),
    "story_corroboration": ("story_id",),
    "story_disagreement": ("story_id",),
    "story_claims": ("story_id",),
    "story_reviews": ("story_id",),
    "story_embeddings": ("story_id",),
    "story_gist": ("story_id",),
}

#: Columns that reference `events.id`. Shifted like every other id, then
#: re-resolved through the natural key — see the module docstring. The bool is
#: whether the column may be NULL, in which case a row that fails to resolve
#: keeps its other meaning and is emptied instead of dropped.
EVENT_REFS: dict[str, tuple[tuple[str, bool], ...]] = {
    "story_members": (("event_id", False),),
    "story_sensor_checks": (("matched_event_id", True),),
}


def dsn() -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )


def columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def max_id(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT coalesce(max(id), 0) FROM public.{table}").fetchone()[0]


def load_csv(conn: psycopg.Connection, table: str, path: Path) -> int:
    """COPY one gzipped CSV into its staging table. Returns rows loaded."""
    with (
        gzip.open(path, "rb") as fh,
        conn.cursor().copy(f"COPY staging.{table} FROM STDIN WITH CSV HEADER") as copy,
    ):
        while block := fh.read(1 << 20):
            copy.write(block)
    return conn.execute(f"SELECT count(*) FROM staging.{table}").fetchone()[0]


def run(bundle_dir: Path, *, dry_run: bool) -> dict:
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    report: dict[str, object] = {"manifest": manifest, "inserted": {}, "dropped_refs": {}}

    with psycopg.connect(dsn()) as conn:
        here = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        here_version = here[0] if here else None
        if here_version != manifest["schema_version"]:
            raise SystemExit(
                f"schema mismatch: bundle is {manifest['schema_version']}, "
                f"this database is {here_version}. Migrate one to match the other first."
            )
        report["schema_version"] = here_version

        tables = [t for t in manifest["tables"] if (bundle_dir / f"{t}.csv.gz").exists()]

        conn.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        conn.execute("CREATE SCHEMA staging")
        try:
            # No constraints or defaults on the staging copies: they hold the
            # source's values verbatim, including ids a default would overwrite,
            # and a unique constraint here would reject rows before the merge
            # has had its say about them.
            for table in tables:
                conn.execute(f"CREATE TABLE staging.{table} (LIKE public.{table})")
                load_csv(conn, table, bundle_dir / f"{table}.csv.gz")

            offsets = {t: max_id(conn, t) for t in tables if "id" in columns(conn, t)}
            for table, offset in offsets.items():
                if offset:
                    conn.execute(f"UPDATE staging.{table} SET id = id + {offset}")

            story_offset = offsets.get("stories", 0)
            if story_offset:
                for table, cols in STORY_REFS.items():
                    if table not in tables:
                        continue
                    for col in cols:
                        conn.execute(f"UPDATE staging.{table} SET {col} = {col} + {story_offset}")

            #: Event references move with the events they name, even though they
            #: are resolved by natural key afterwards. Leaving them unshifted
            #: looks right — the resolver is about to overwrite them — but the
            #: resolver finds its event by matching this column against
            #: `staging.events.id`, which has already moved. Unshifted, nothing
            #: matches, every reference reads as unresolvable, and the whole
            #: story graph is dropped as dangling.
            events_offset = offsets.get("events", 0)
            if events_offset:
                for table, cols in EVENT_REFS.items():
                    if table not in tables:
                        continue
                    for col, _nullable in cols:
                        conn.execute(
                            f"UPDATE staging.{table} SET {col} = {col} + {events_offset} "
                            f"WHERE {col} IS NOT NULL"
                        )

            # Events first: every later step needs to know which row won.
            insert_order = ["events"] + [t for t in tables if t != "events"]
            for table in insert_order:
                if table not in tables:
                    continue
                if table == "events":
                    cols = ", ".join(f'"{c}"' for c in columns(conn, table))
                    inserted = conn.execute(
                        f"INSERT INTO public.{table} ({cols}) SELECT {cols} FROM staging.{table} "
                        "ON CONFLICT DO NOTHING"
                    ).rowcount
                    report["inserted"][table] = inserted
                    _resolve_event_refs(conn, tables, report)
                    continue
                cols = ", ".join(f'"{c}"' for c in columns(conn, table))
                report["inserted"][table] = conn.execute(
                    f"INSERT INTO public.{table} ({cols}) SELECT {cols} FROM staging.{table} "
                    "ON CONFLICT DO NOTHING"
                ).rowcount

            # Sequences must clear the shifted ids or the next insert collides
            # with a row that is already there.
            for table in offsets:
                conn.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"GREATEST((SELECT coalesce(max(id), 1) FROM public.{table}), 1))",
                    (f"public.{table}",),
                )

            if dry_run:
                conn.rollback()
                report["rolled_back"] = True
            else:
                conn.commit()
                report["rolled_back"] = False
        finally:
            conn.execute("DROP SCHEMA IF EXISTS staging CASCADE")
            conn.commit()
    return report


def _resolve_event_refs(conn: psycopg.Connection, tables: list[str], report: dict) -> None:
    """Point event references at whichever row won the insert.

    Joined on the natural key rather than the shifted id, because a duplicate
    event kept the destination's row and the destination's id.
    """
    for table, cols in EVENT_REFS.items():
        if table not in tables:
            continue
        for col, nullable in cols:
            conn.execute(
                f"""
                UPDATE staging.{table} s
                   SET {col} = e.id
                  FROM staging.events se
                  JOIN public.events e
                    ON e.source = se.source AND e.source_event_id = se.source_event_id
                 WHERE s.{col} = se.id
                """
            )
            unresolved = f"""
                {col} IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM public.events e WHERE e.id = s.{col}
                )
            """
            n = conn.execute(
                f"SELECT count(*) FROM staging.{table} s WHERE {unresolved}"
            ).fetchone()[0]
            if n:
                report["dropped_refs"][f"{table}.{col}"] = n
            if nullable:
                conn.execute(f"UPDATE staging.{table} s SET {col} = NULL WHERE {unresolved}")
            else:
                conn.execute(f"DELETE FROM staging.{table} s WHERE {unresolved}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="do everything, then roll it all back"
    )
    args = parser.parse_args()

    report = run(args.bundle_dir, dry_run=args.dry_run)
    print(f"schema {report['schema_version']}  rolled_back={report['rolled_back']}")
    for table, n in report["inserted"].items():
        print(f"  {table:24} {n:>10,}")
    for ref, n in report["dropped_refs"].items():
        print(f"  dropped {ref:16} {n:>10,}")


if __name__ == "__main__":
    main()
