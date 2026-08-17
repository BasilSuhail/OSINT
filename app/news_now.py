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


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args:
        print(f"  {__name__} takes no arguments (got {' '.join(args)})", file=sys.stderr)
        return 2

    print(f"Building {len(_STAGES)} stage(s), in order.\n")
    width = max(len(name) for name, _, _ in _STAGES)
    failed: list[str] = []

    for name, produces, task in _STAGES:
        print(f"  {name:<{width}}  {produces}")
        try:
            outcome = task()
        #: Broad, and each stage still attempted: a brain stage that declines
        #: because the box is busy must not stop the clustering that would have
        #: worked, and the failure is worth naming rather than hiding.
        except Exception as exc:
            failed.append(name)
            print(f"  {'':<{width}}  failed — {type(exc).__name__}: {exc}\n")
            continue
        print(f"  {'':<{width}}  {_describe(outcome)}\n")

    if failed:
        print(f"{len(failed)} stage(s) failed: {', '.join(failed)}")
    #: The brain declines when the box has no headroom, by design, and reports
    #: that as a reason rather than an error. A skipped narrative is not a
    #: failure of this command, so the exit code does not pretend otherwise.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
