"""Shrink footprint geometry stored before the per-event byte budget (#613).

Enrichment applies `fit_to_budget` from now on, but rows enriched earlier still
carry the full upstream geometry — up to 2 MB per event, paid for on every map
refresh. This re-simplifies them in place. No refetch, no network.

Dry run by default: it reports the saving and changes nothing.

    uv run python scripts/backfill_footprint_budget.py            # report
    uv run python scripts/backfill_footprint_budget.py --apply    # write
"""

import argparse

from sqlalchemy import select

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.footprint import FOOTPRINT_BYTE_BUDGET, fit_to_budget, geojson_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the simplified geometry")
    args = parser.parse_args()

    scanned = shrunk = before = after = 0
    with session_scope() as session:
        stmt = select(EventRow).where(EventRow.payload["footprint_geojson"].as_string().isnot(None))
        for row in session.execute(stmt).scalars():
            payload = dict(row.payload or {})
            fc = payload.get("footprint_geojson")
            if not isinstance(fc, dict):
                continue
            scanned += 1
            size = geojson_bytes(fc)
            before += size
            if size <= FOOTPRINT_BYTE_BUDGET:
                after += size
                continue
            fitted = fit_to_budget(fc)
            after += geojson_bytes(fitted)
            shrunk += 1
            if args.apply:
                payload["footprint_geojson"] = fitted
                row.payload = payload  # reassign so SQLAlchemy flags the jsonb dirty
        if not args.apply:
            session.rollback()

    print(
        f"{scanned:,} footprint(s) scanned, {shrunk:,} over the {FOOTPRINT_BYTE_BUDGET:,}B budget"
    )
    print(f"  {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
    if not args.apply:
        print("dry run — re-run with --apply to write.")


if __name__ == "__main__":
    main()
