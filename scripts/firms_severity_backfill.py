"""Report — and optionally write — severity on FIRMS rows stored before #574 (#577).

Dry run by default: it prints what it would set and changes nothing. Writing is
a separate, explicit `--apply`, because this mutates rows the composite reads
and the counts are worth checking against the source first.

    uv run python scripts/firms_severity_backfill.py            # report
    uv run python scripts/firms_severity_backfill.py --apply    # write

The composite still holds scores computed while these rows were NULL. Re-run it
after applying, or the fix will not show up in anything user-visible.
"""

import argparse

from app.db import session_scope
from app.sources import firms_backfill


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the reported severities")
    args = parser.parse_args()

    with session_scope() as session:
        plan = firms_backfill.plan_backfill(session)

        for group in plan.groups:
            print(
                f"  confidence {group.confidence_raw!r} -> severity {group.severity}"
                f"  ({group.rows:,} rows)"
            )
        print(f"{plan.total_rows:,} row(s) can recover a severity from payload.confidence_raw.")
        if plan.unrecoverable_rows:
            print(f"{plan.unrecoverable_rows:,} row(s) carry no readable confidence and stay NULL.")

        if not plan.total_rows:
            print("nothing to do.")
            return
        if not args.apply:
            print("dry run — nothing written. Re-run with --apply to write these.")
            return

        updated = firms_backfill.apply_backfill(session, plan)
        print(f"set severity on {updated:,} row(s).")
        print("the composite's stored scores predate this — re-run it to pick the rows up.")


if __name__ == "__main__":
    main()
