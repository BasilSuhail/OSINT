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

#: How many stories a quick run gists. Matches what the scheduled task does per
#: pass, so `make news` costs what it always did — the change is that you can
#: watch it rather than wait blind.
_QUICK_TARGET = 20

#: Stories per step. Small enough that the bar moves several times inside a
#: quick run, large enough that the per-call overhead stays negligible against a
#: model generation that takes seconds.
_STEP = 4


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
    if not done:
        eta = "estimating"
    else:
        remaining = elapsed / done * max(total - done, 0)
        #: Minutes once there are minutes left, seconds below that, and "nearly
        #: done" only when it really is — saying that at 4 of 20 is a lie the
        #: reader can check against the counts on the same line.
        if remaining >= 60:
            eta = f"~{remaining / 60:.0f} min left"
        elif remaining >= 5:
            eta = f"~{remaining:.0f}s left"
        else:
            eta = "nearly done"
    return f"[{'#' * filled}{'.' * (_BAR - filled)}] {done}/{total} stories, {eta}"


def _enrich_batch(size: int) -> dict[str, Any]:
    """Gist up to `size` stories, honouring the same headroom gate as the task.

    The Celery task takes no batch size — it is written for a schedule, where a
    fixed twenty per run is the right shape. Driving it in smaller steps is what
    makes progress visible, so the body is called directly with a size, the way
    `app/brain/enrich_run.py` already does for `make enrich`.

    The gate is re-checked here rather than skipped: gisting is model work, and
    the reason the task declines on a loaded box applies just as much when a
    person asked for it.
    """
    from app.tasks import _skip_optional_heavy

    if skipped := _skip_optional_heavy():
        return skipped
    from app.brain.enrich import _enrich_body

    return _enrich_body(batch_limit=size)


def _gist(
    *,
    target: int | None,
    step: int,
    indent: int = 11,
    enrich: Callable[[int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Gist stories in visible steps, up to `target`, or the whole window if None.

    One call gisting twenty stories takes minutes on a small box and prints
    nothing until it returns, which is indistinguishable from a hang. Several
    smaller calls take the same time and can be counted, which is the whole
    difference: `target=20, step=4` is five steps and a bar that moves.

    Stops when a step gists nothing — the window is done — or when the brain
    declines for want of headroom, because calling again would spin.
    """
    #: Resolved here, not as a default argument: a default binds the function
    #: once, at import, so anything that replaces it afterwards is ignored.
    enrich = enrich or _enrich_batch
    started = time.monotonic()
    total = 0
    done = 0
    #: A terminal gets one line rewritten; a pipe or `docker compose exec -T`
    #: gets one line per step, because \r in a log file is unreadable.
    live = sys.stdout.isatty()

    while True:
        size = step if target is None else min(step, target - done)
        if size <= 0:
            break
        outcome = enrich(size)
        if not isinstance(outcome, dict) or outcome.get("reason"):
            #: Declined rather than finished — say why rather than reporting a
            #: total that would look like success.
            return outcome if isinstance(outcome, dict) else {"state": str(outcome)}
        total = int(outcome.get("window_stories") or total)
        gisted = int(outcome.get("enriched") or 0)
        #: A step that found nothing is the end of the window, not progress.
        #: Drawing the bar again would repeat the previous line verbatim.
        if gisted == 0:
            break
        done += gisted
        #: The bar counts towards what this run is trying to do, not the whole
        #: window — a quick run reaching 20/20 has finished what it promised, and
        #: the summary afterwards says how much of the window that was.
        line = f"{' ' * indent}{_bar(done, target or total, started)}"
        print(f"\r{line}" if live else line, end="" if live else "\n", flush=True)

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
        #: Gisting is the only stage measured in stories rather than in one pass,
        #: so it is the only one that can show progress — and the only one long
        #: enough to need to. Both modes go through the same loop; they differ in
        #: how far they go, not in what they report.
        gisting = name == "gist"
        try:
            if gisting:
                outcome = _gist(
                    target=None if every else _QUICK_TARGET,
                    step=_STEP,
                    #: Line up under the stage's own description, whatever the
                    #: longest stage name happens to be.
                    indent=width + 4,
                )
            else:
                outcome = task()
        #: Broad, and each stage still attempted: a brain stage that declines
        #: because the box is busy must not stop the clustering that would have
        #: worked, and the failure is worth naming rather than hiding.
        except Exception as exc:
            failed.append(name)
            print(f"  {'':<{width}}  failed — {type(exc).__name__}: {exc}\n")
            continue
        #: The bar has already said what happened, line by line. Repeating it as
        #: a summary would be the same numbers twice.
        if gisting:
            print()
        else:
            print(f"  {'':<{width}}  {_describe(outcome)}\n")
        if gisting and isinstance(outcome, dict):
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
