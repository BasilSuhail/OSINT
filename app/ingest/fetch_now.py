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

It lives here rather than in ``scripts/`` because it runs *inside* the worker
container, and the image copies ``app/`` but not ``scripts/`` — deliberately, as
most of that directory is host-side tooling that runs before any container
exists. Put in ``scripts/`` first, this command raised ``ModuleNotFoundError`` on
every invocation (#995).

    python -m app.ingest.fetch_now              # every registered fetcher
    python -m app.ingest.fetch_now gdelt usgs-quake
"""

from __future__ import annotations

import sys
from typing import Any

from app.fetcher_registry import registered_names
from app.sources.base import SourceMisconfiguredError
from app.tasks import run_fetcher

#: States `run_fetcher` returns for a source that is switched off rather than
#: broken: no API key, or a licensed CSV nobody has downloaded. It catches
#: `SourceMisconfiguredError` itself and reports it as a state, so the exception
#: never reaches here and a run of these looked identical to a run of failures.
_DORMANT_STATES = frozenset({"misconfigured"})


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
    #: From the names actually being run, not a constant. The longest is 26
    #: characters and a hard-coded 22 ran the state into the name.
    width = max(len(name) for name in names)

    for name in names:
        try:
            outcome = run_fetcher(name)
        except SourceMisconfiguredError as exc:
            dormant.append(name)
            result = f"dormant — {exc}"
        #: Broad on purpose: one source with an expired feed, a rate limit or a
        #: DNS failure must not stop the other nineteen from running.
        except Exception as exc:
            failed.append(name)
            result = f"failed — {type(exc).__name__}: {exc}"
        else:
            state = str(outcome.get("state", "?"))
            if state in _DORMANT_STATES:
                dormant.append(name)
            elif state == "failed":
                failed.append(name)
            rows += int(outcome.get("inserted") or 0)
            result = _describe(outcome)
        #: One complete line, printed after the call rather than a name before it
        #: and a state after. Fetchers log to the same stream while they work —
        #: one feed emitted 25 translation warnings — and a half-written line
        #: with a page of logs dropped into the middle of it is unreadable.
        print(f"  {name:<{width}}  {result}", flush=True)

    print(f"\n{rows} new row(s).")
    if dormant:
        print(f"{len(dormant)} dormant, for want of a key or a file: {', '.join(dormant)}")
        print("  A configuration choice, not a fault — see env.example.")
    if failed:
        print(f"{len(failed)} failed: {', '.join(failed)}")
        #: A feed answering 403 is put in a timed quarantine and retried later,
        #: which is the backoff working rather than something to go and fix.
        print("  A feed refusing today is quarantined and retried; it needs nothing from you.")
    #: Zero regardless. A dormant source is expected, and a network hiccup on one
    #: feed is not a reason for `make fetch` to look like it broke.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
