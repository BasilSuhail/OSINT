"""One-shot CLI — build the country-month panel and export it.

Usage:
    python -m app.panel.run           # writes $OSINT_DATA_DIR/exports/
    make panel
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.composite.config import DEFAULT_METHOD_VERSION
from app.db import get_engine
from app.db_models import LabelRow, ScoreRow
from app.labels.acled_loader import load_acled_weekly
from app.panel.assemble import assemble_panel
from app.panel.export import export_panel
from app.panel.spine import build_spine, coverage_windows
from app.settings import settings

_SCORE_NAME = "composite"


def main() -> int:
    if not settings.acled_csv_dir:
        print("ACLED_CSV_DIR is not set — cannot derive coverage windows.", file=sys.stderr)
        return 1
    try:
        loaded = load_acled_weekly(settings.acled_csv_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    spine = build_spine(coverage_windows(loaded.rows))

    with Session(get_engine()) as session:
        label_rows = [
            {
                "country": row.country,
                "bucket_start": row.bucket_start,
                "label_code": row.label_code,
                "magnitude": row.magnitude,
            }
            for row in session.execute(select(LabelRow)).scalars()
        ]
        score_rows = [
            {
                "country": row.country,
                "bucket_start": row.bucket_start,
                "score_value": row.score_value,
                "components": row.components,
                "method_version": row.method_version,
            }
            for row in session.execute(
                select(ScoreRow).where(
                    ScoreRow.score_name == _SCORE_NAME,
                    ScoreRow.method_version == DEFAULT_METHOD_VERSION,
                )
            ).scalars()
        ]

    panel = assemble_panel(spine, label_rows, score_rows)
    out_dir = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    meta = export_panel(panel, out_dir)

    print(f"panel exported to {out_dir}")
    print(f"  rows        : {meta['rows']}")
    print(f"  countries   : {meta['countries']}")
    print(f"  span        : {meta['span']}")
    print(f"  labels      : {meta['label_counts']}")
    print(f"  score rows  : {meta['score_rows']}")
    if not label_rows:
        print("  warning     : labels table is empty — run `make labels` first")
    if meta["score_rows"] == 0:
        print("  note        : no composite scores yet (expected before backfill)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
