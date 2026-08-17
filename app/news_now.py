"""Build the stories, the cards and the written summary, now (#997).

`make fetch` fills the map. It collects raw events, and everything on the left of
the console is downstream of that: the rolling news window has to be clustered
into stories, each story needs a gist before it can be drawn as a card, and the
situation summary is written from the clusters.

Beat runs all three on a schedule — clustering every 30 minutes, gists every 20,
the narrative every 15 — so a console left alone fills itself. But clustering has
to finish before the narrative can read it, so from a standing start the wait is
one 30-minute cycle plus one 15-minute cycle, during which the map is full and
the situation card says "No stories in the window yet". Two halves of one screen
arriving three quarters of an hour apart, with nothing saying which is which,
reads as a fault.

This is the other half of `make fetch`: raw events in, meaning out.

Order is the point. Clustering first, because the gist and the narrative both
read clusters; gists second, because a story with no gist cannot be drawn as a
card; the narrative last, because it summarises what the first two produced.
Running them in any other order produces a console that looks half-built.

Lives at the top of `app/` rather than under `ingest/`, `stories/` or `brain/`
because it belongs to none of them — it is the sequence, and putting it inside
any one step would imply that step owns the other two.

    python -m app.news_now
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from app.tasks import brain_enrich, brain_narrate, cluster_stories

#: The pipeline, in the only order that works. Each entry is what it produces on
#: screen, not what the function is called — somebody running this wants to know
#: which part of the console is being built.
_STAGES: tuple[tuple[str, str, Callable[[], dict[str, Any]]], ...] = (
    ("cluster", "story clusters from the news window", cluster_stories),
    ("gist", "the summary line on each story card", brain_enrich),
    ("narrate", "the written situation summary", brain_narrate),
)

#: Width of the drawn bar. Narrow enough to survive an 80-column terminal
#: alongside the counts and the estimate.
_BAR = 24


def _describe(outcome: dict[str, Any]) -> str:
    """What a stage did, from the dict its task returns.

    The tasks do not share a result shape — clustering counts stories, the brain
    reports whether it persisted and why it declined — so this reports what is
    there rather than assuming a schema that does not exist.
    """
    if not isinstance(outcome, dict):
        return str(outcome)
    if reason := outcome.get("reason"):
        persisted = outcome.get("persisted")
        prefix = "written" if persisted else "skipped"
        return f"{prefix} — {reason}"
    interesting = {k: v for k, v in outcome.items() if v not in (None, 0, "", [])}
    return ", ".join(f"{k}={v}" for k, v in interesting.items()) or "nothing to do"


def _bar(done: int, total: int, started: float) -> str:
    """A progress line with an estimate, for a stage measured in hours.

    Gisting is one model generation per story. On a small box that is seconds
    each, so a thousand stories is hours — and an estimate the reader can act on
    is the difference between waiting and wondering whether it has hung.
    """
    total = max(total, 1)
    filled = min(_BAR, round(_BAR * done / total))
    elapsed = time.monotonic() - started
    if done:
        remaining = elapsed / done * max(total - done, 0)
        eta = f"~{remaining / 60:.0f} min left" if remaining >= 60 else "nearly done"
    else:
        eta = "estimating"
    return f"[{'#' * filled}{'.' * (_BAR - filled)}] {done}/{total} stories, {eta}"


def _gist_everything(*, enrich: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Gist every story in the window, one batch at a time, reporting as it goes.

    The task gists a bounded batch per call — twenty — because it normally runs
    on a schedule where finishing is not the point. Called once, that leaves the
    great majority of a first fill undone and nothing saying so. Called until it
    stops finding work, it finishes, and the caller can see how far along it is.

    Stops when a batch enriches nothing: either the window is done, or the box
    declined for want of headroom and repeating it would spin.
    """
    #: Resolved here, not as a default argument: a default binds the function
    #: object once, when this module is imported, so anything that replaces
    #: `brain_enrich` afterwards is silently ignored.
    enrich = enrich or brain_enrich
    started = time.monotonic()
    total = 0
    done = 0
    #: A terminal gets one line rewritten; a pipe or `docker compose exec -T`
    #: gets one line per batch, because \r in a log file is unreadable.
    live = sys.stdout.isatty()

    while True:
        outcome = enrich()
        if not isinstance(outcome, dict) or outcome.get("reason"):
            #: Declined rather than finished — say why rather than reporting a
            #: total that would look like success.
            return outcome if isinstance(outcome, dict) else {"state": str(outcome)}
        total = int(outcome.get("window_stories") or total)
        batch = int(outcome.get("enriched") or 0)
        done += batch
        line = f"           {_bar(done, total, started)}"
        print(f"\r{line}" if live else line, end="" if live else "\n", flush=True)
        if batch == 0:
            break

    if live:
        print()
    return {"window_stories": total, "enriched": done}


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    every = "--all" in args
    leftover = [arg for arg in args if arg != "--all"]
    if leftover:
        print(f"  unknown argument: {' '.join(leftover)} (only --all)", file=sys.stderr)
        return 2

    print(f"Building {len(_STAGES)} stage(s), in order.\n")
    width = max(len(name) for name, _, _ in _STAGES)
    failed: list[str] = []
    short: str | None = None

    for name, produces, task in _STAGES:
        print(f"  {name:<{width}}  {produces}")
        #: The gist stage is the only unbounded one. Left to the task it does a
        #: batch of twenty, which on a first fill of a thousand stories is a
        #: rounding error — and the run reports a number that looks finished.
        runner = (lambda: _gist_everything()) if (every and name == "gist") else task
        try:
            outcome = runner()
        #: Broad, and each stage still attempted: a brain stage that declines
        #: because the box is busy must not stop the clustering that would have
        #: worked, and the failure is worth naming rather than hiding.
        except Exception as exc:
            failed.append(name)
            print(f"  {'':<{width}}  failed — {type(exc).__name__}: {exc}\n")
            continue
        if not (every and name == "gist"):
            print(f"  {'':<{width}}  {_describe(outcome)}\n")
        else:
            print()
        if name == "gist" and isinstance(outcome, dict):
            total = int(outcome.get("window_stories") or 0)
            enriched = int(outcome.get("enriched") or 0)
            if total > enriched:
                short = f"{enriched} of {total} stories have a gist"

    if short:
        print(f"{short}. The rest fill in on the schedule, roughly 20 every 20 minutes.")
        print("  To do them all now instead — hours on a small box — run `make news-all`.")
    if failed:
        print(f"{len(failed)} stage(s) failed: {', '.join(failed)}")
    #: The brain declines when the box has no headroom, by design, and reports
    #: that as a reason rather than an error. A skipped narrative is not a
    #: failure of this command, so the exit code does not pretend otherwise.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
