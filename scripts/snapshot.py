#!/usr/bin/env python
"""Snapshot the local Postgres tables to local gzipped CSV.

A lightweight "so I can roll back to when it worked" backup. Streams each
table out via server-side ``COPY ... TO STDOUT WITH CSV HEADER`` straight
into a gzip file, so it stays memory-light even for the ~300k-row ``events``
table and needs no ``pg_dump`` (our Homebrew pg_dump is v14 while the local
Postgres may run a newer version, so pg_dump version mismatches can occur).

Why CSV and not Parquet: ``pyarrow`` is not a project dependency, and CSV
restores with a plain ``COPY ... FROM``. Why not the SQLAlchemy engine:
``COPY`` is an order of magnitude faster and does not buffer the whole
table in Python.

Usage
-----
    python -m scripts.snapshot                       # all default tables
    python -m scripts.snapshot --skip events         # everything but events
    python -m scripts.snapshot --tables scores labels # just these
    python -m scripts.snapshot --tag                 # also git-tag HEAD

Output
------
    backups/<UTC-timestamp>/<table>.csv.gz
    backups/<UTC-timestamp>/manifest.json   # git sha + per-table row counts

Restore one table (psql against the same DB):
    gunzip -c backups/<ts>/scores.csv.gz | \
      psql "$DSN" -c "COPY scores FROM STDIN WITH CSV HEADER"
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from app.settings import settings

# Tables worth snapshotting, largest last. ``alembic_version`` is included so
# a restore knows which migration the dump matches.
DEFAULT_TABLES = [
    "alembic_version",
    "scores",
    "labels",
    "notifications",
    "ingest_health",
    "ingest_failures",
    "dead_letter_queue",
    "housekeeping_runs",
    "events",
]


def _dsn() -> str:
    """libpq connection string from the same settings the app uses."""
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password} sslmode=require"
    )


def _git_sha() -> str | None:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _dump_table(conn: psycopg.Connection, table: str, dest: Path) -> int:
    """COPY one table to a gzipped CSV. Returns the row count."""
    rows = 0
    with conn.cursor() as cur, gzip.open(dest, "wb") as fh:
        with cur.copy(f'COPY (SELECT * FROM "{table}") TO STDOUT WITH CSV HEADER') as copy:
            for chunk in copy:
                fh.write(chunk)
        # rowcount is -1 for COPY TO; count via the cursor instead.
        cur.execute(f'SELECT count(*) FROM "{table}"')
        rows = cur.fetchone()[0]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot Postgres tables to gzipped CSV.")
    ap.add_argument("--tables", nargs="+", help="Only these tables (default: all known).")
    ap.add_argument("--skip", nargs="+", default=[], help="Tables to exclude.")
    ap.add_argument("--out", default="backups", help="Output root dir (default: backups).")
    ap.add_argument("--tag", action="store_true", help="Also create a git tag for HEAD.")
    args = ap.parse_args()

    tables = [t for t in (args.tables or DEFAULT_TABLES) if t not in args.skip]
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = _git_sha()
    manifest: dict[str, object] = {
        "created_at": ts,
        "git_sha": sha,
        "database": settings.postgres_db,
        "host": settings.postgres_host,
        "tables": {},
    }

    print(f"snapshot → {out_dir}  (git {sha[:8] if sha else 'unknown'})")
    with psycopg.connect(_dsn(), connect_timeout=15) as conn:
        for table in tables:
            dest = out_dir / f"{table}.csv.gz"
            try:
                rows = _dump_table(conn, table, dest)
            except psycopg.Error as exc:
                conn.rollback()
                print(f"  ✗ {table}: {exc}")
                manifest["tables"][table] = {"error": str(exc)}
                continue
            size = dest.stat().st_size
            manifest["tables"][table] = {"rows": rows, "bytes": size}
            print(f"  ✓ {table:18} {rows:>8} rows  {size / 1024:.0f} KiB")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if args.tag and sha:
        tag = f"snapshot/{ts}"
        try:
            subprocess.check_call(["git", "tag", "-a", tag, "-m", f"DB snapshot {ts}"])
            print(f"git tag {tag} (push with: git push origin {tag})")
        except subprocess.CalledProcessError as exc:
            print(f"git tag failed: {exc}")

    print(f"done → {out_dir}/manifest.json")


if __name__ == "__main__":
    main()
