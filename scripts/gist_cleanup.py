"""Report — and optionally delete — stored gists carrying invented figures (#553).

Dry run by default: it prints what it objects to and changes nothing. Deleting
is a separate, explicit `--apply`, because a strict numeral check flags a few
defensible gists ("two immigrants" grounded only by two names) and the output
is worth reading first.

    uv run python scripts/gist_cleanup.py            # report
    uv run python scripts/gist_cleanup.py --apply    # delete what it reports
"""

import argparse

from app.brain import gist_cleanup, numerals
from app.db import session_scope


def _format(offender: gist_cleanup.Offender) -> str:
    figures = ", ".join(numerals.format_figure(v) for v in offender.figures)
    lines = [f"story {offender.story_id}  ungrounded: {figures}", f"  gist: {offender.gist}"]
    lines += [f"  headline: {t}" for t in offender.titles[:3]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete the reported rows")
    args = parser.parse_args()

    with session_scope() as session:
        offenders = gist_cleanup.find_offenders(session)
        for offender in offenders:
            print(_format(offender))
            print()
        print(f"{len(offenders)} gist(s) carry figures their headlines do not.")
        if not args.apply:
            print("dry run — nothing deleted. Re-run with --apply to delete these.")
            return
        deleted = gist_cleanup.delete_offenders(session, offenders)
        print(f"deleted {deleted} gist(s); stories still in the enrich window will re-gist.")


if __name__ == "__main__":
    main()
