"""One-shot CLI — load ACLED aggregates, compute P1-P3, upsert, summarise.

Usage:
    python -m app.labels.run          # reads ACLED_CSV_DIR from settings
    make labels

Idempotent: rerunning refreshes existing rows in place.
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy.orm import Session

from app.db import get_engine
from app.labels.acled_loader import load_acled_weekly
from app.labels.persistence import purge_label_source, upsert_labels
from app.labels.rules import RULES_VERSION, compute_labels
from app.settings import settings


def _run() -> int:
    directory = settings.acled_csv_dir
    if not directory:
        print("ACLED_CSV_DIR is not set — nothing to label.", file=sys.stderr)
        return 1

    try:
        loaded = load_acled_weekly(directory)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    labels = compute_labels(loaded.rows)
    with Session(get_engine()) as session:
        purged = purge_label_source(session)
        affected = upsert_labels(labels, session)

    per_code = Counter(label["label_code"] for label in labels)
    countries = {label["country"] for label in labels}
    months = sorted(label["bucket_start"] for label in labels)

    print(f"labels {RULES_VERSION} — {affected} rows written ({purged} prior rows purged)")
    print(f"  files read      : {len(loaded.files_read)}")
    print(f"  tidy rows       : {len(loaded.rows)} (skipped {loaded.skipped_rows} malformed)")
    for code in sorted(per_code):
        print(f"  {code:<15} : {per_code[code]}")
    print(f"  countries       : {len(countries)}")
    if months:
        print(f"  span            : {months[0].date()} → {months[-1].date()}")
    if loaded.unmapped_countries:
        names = ", ".join(f"{name} ({n})" for name, n in loaded.unmapped_countries.most_common())
        print(f"  unmapped names  : {names}")
    return 0


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("labels"):
        rc = _run()
        if rc != 0:
            raise SystemExit(f"labels: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
