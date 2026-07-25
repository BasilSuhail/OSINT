"""Report — and optionally write — FRP-derived severity on stored FIRMS rows (#579).

Dry run by default: it prints what it would change and writes nothing. Writing
is a separate, explicit `--apply`, because this mutates rows the composite reads
and the counts are worth checking against the source first.

    uv run python scripts/firms_frp_resweep.py            # report
    uv run python scripts/firms_frp_resweep.py --apply    # write

Replaces scripts/firms_severity_backfill.py, which recovered the same rows from
`payload.confidence_raw` — the right value of the wrong quantity.

The composite still holds scores computed under the old encoding, and #579 also
moved FIRMS into its own `wildfire` domain, so the method version is now v3.0.
Re-run the composite after applying, or none of this reaches anything
user-visible.
"""

import argparse

from app.db import session_scope
from app.sources import firms_frp_resweep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the derived severities")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=firms_frp_resweep.DEFAULT_BATCH_SIZE,
        help="rows per UPDATE (default: %(default)s)",
    )
    args = parser.parse_args()

    with session_scope() as session:
        plan = firms_frp_resweep.plan_resweep(session)

        print(f"{plan.total_rows:,} FIRMS row(s) stored.")
        print(f"  {plan.rewritable_rows:,} would change to an FRP-derived severity.")
        print(f"  {plan.unchanged_rows:,} already hold that value.")
        if plan.unreadable_rows:
            print(
                f"  {plan.unreadable_rows:,} carry no readable frp/confidence "
                "and will be set to NULL."
            )

        if not plan.rewritable_rows and not plan.unreadable_rows:
            print("nothing to do.")
            return
        if not args.apply:
            print("dry run — pass --apply to write.")
            return

        changed = firms_frp_resweep.apply_resweep(session, batch_size=args.batch_size)
        print(f"{changed:,} row(s) updated.")
        print("re-run the composite to pick this up.")


if __name__ == "__main__":
    main()
