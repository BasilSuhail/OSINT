"""Run every fetcher once, now, and say what each one did (#993).

A fresh install has an empty database. Beat runs the fetchers on a schedule —
five minutes for markets, quarter-hours for GDELT — so the first rows arrive
somewhere between one and fifteen minutes after `make up`. Until then every
panel reads zero and the story feed says there is nothing in the window, which
is indistinguishable from an install that did not work.

This is the command that fills it immediately. It exists because priming the
database by hand meant knowing the fetcher registry, the Celery task name, and
that it has to run inside the worker container — reconstructed from source, one
fetcher at a time, by somebody who should not have needed to.

A source that needs an API key nobody has is reported as **dormant**, not as a
failure. "No data from this source" and "this source needs a key" look identical
on the console, and only one of them is worth doing anything about.

Sequential on purpose: this runs on a small machine, several fetchers download
megabytes, and doing them at once is how a Pi runs out of memory. Slow and
legible beats fast and unexplained.

    python -m scripts.fetch_now              # every registered fetcher
    python -m scripts.fetch_now gdelt usgs-quake
"""

from __future__ import annotations

import sys
from typing import Any

from app.fetcher_registry import registered_names
from app.sources.base import SourceMisconfiguredError
from app.tasks import run_fetcher

#: Printed width for the source column, so the states line up and a run of
#: twenty sources can be read down rather than across.
_WIDTH = 22


def _describe(outcome: dict[str, Any]) -> str:
    """One line for what a fetch did, from the state dict the task returns."""
    state = outcome.get("state", "?")
    inserted = outcome.get("inserted")
    fetched = outcome.get("fetched")
    if inserted is None and fetched is None:
        return str(state)
    return f"{state} (fetched {fetched}, new {inserted})"


def main(argv: list[str] | None = None) -> int:
    wanted = list(argv if argv is not None else sys.argv[1:])
    names = sorted(wanted) if wanted else sorted(registered_names())

    unknown = [name for name in names if name not in registered_names()]
    if unknown:
        print(f"  no such fetcher: {', '.join(unknown)}", file=sys.stderr)
        return 2

    print(f"Running {len(names)} fetcher(s). Sources needing a key stay dormant.\n")
    dormant: list[str] = []
    failed: list[str] = []
    rows = 0

    for name in names:
        print(f"  {name:<{_WIDTH}}", end="", flush=True)
        try:
            outcome = run_fetcher(name)
        except SourceMisconfiguredError as exc:
            dormant.append(name)
            print(f"dormant — {exc}")
            continue
        #: Broad on purpose: one source with an expired feed, a rate limit or a
        #: DNS failure must not stop the other nineteen from running.
        except Exception as exc:
            failed.append(name)
            print(f"failed — {type(exc).__name__}: {exc}")
            continue
        rows += int(outcome.get("inserted") or 0)
        print(_describe(outcome))

    print(f"\n{rows} new row(s).")
    if dormant:
        print(f"{len(dormant)} source(s) dormant for want of a key: {', '.join(dormant)}")
        print("  That is a configuration choice, not a fault — see env.example.")
    if failed:
        print(f"{len(failed)} source(s) failed: {', '.join(failed)}")
    #: Zero regardless. A dormant source is expected, and a network hiccup on one
    #: feed is not a reason for `make fetch` to look like it broke.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
