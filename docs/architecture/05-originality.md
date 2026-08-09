# 05 — Independence and provenance

This system was built from nothing. No external source code went into it, and
the public commit history is the evidence. This file records what that means in
practice, what the design descends from, and what it deliberately is not.

- [Where the design came from](#where-the-design-came-from)
- [What the architecture shares with everything else](#what-the-architecture-shares-with-everything-else)
- [Where the substance is](#where-the-substance-is)
- [What is claimed, precisely](#what-is-claimed-precisely)
- [Provenance trail](#provenance-trail)

---

## Where the design came from

Publicly visible open-source intelligence systems demonstrated that a useful
live map could run on commodity hardware. That was the extent of the influence:
a working existence proof, seen from the outside.

The rule that follows from it is simple and absolute. **No source file, no
fragment, no line came from anywhere else.** Nothing external was open while
this was written. The architecture was chosen for the constraints in front of
it — a single-board machine, a fixed storage budget, a composite whose data
flow has particular needs — and not by reference to how anyone else solved a
different problem.

The systems that prompted the design are not named here. Naming them would
invite exactly one question — how much of this is theirs — and answer it worse
than a description of the design does. The ideas involved are held in common by
many systems and invented by none of them.

---

## What the architecture shares with everything else

Honestly: tiered polling cadences, per-source workers, and a map as the primary
surface are shared with many systems. None of these is novel and none belongs
to anyone. A stack of FastAPI, MapLibre and a small always-on machine is the
obvious answer to this problem, arrived at independently by everyone who has
the problem.

Architectural overlap of that kind is evidence of standard, sensible choices.
It is not evidence of derivation, and treating it as either would be a mistake
in both directions.

What distinguishes this system is not the architecture. It is what the
architecture is made to carry.

---

## Where the substance is

A live dashboard answers "what is happening right now" and stops. This system
does not stop there, and that difference is the whole of it:

| | A live dashboard | This system |
| --- | --- | --- |
| **Primary output** | A map of current activity | A multi-modal composite stress figure per country; the map is the secondary surface |
| **After ingest** | Rendering | Severity grading, story clustering, corroboration, divergence, onset detection, coverage audit |
| **Methodology** | Engineering-first, no published evaluation | OECD/JRC 10-step composite indicator handbook, evaluation fixed in advance against a hybrid ground truth |
| **Evaluation** | None | AUROC / AUPR / Brier / lead-time against nine baselines — see [`../methodology.md`](../methodology.md) |
| **Feeds in the core claim** | All of them, surfaced | Three input domains in the composite. Everything else is dashboard breadth and is not claimed as contribution |
| **Being wrong** | Not measured | Recorded. Forecasts are scored and the scoreboard is kept |

The last row is the one that matters. A system that cannot say how often it was
wrong is a display. The engineering here exists to support a measurement, and
the measurement is the contribution.

Against the charge that this is a few free APIs wired to a map: the answer is
not the wiring. It is the composite built by documented procedure over three
heterogeneous domains, the evaluation protocol fixed before any output was
examined, the negative findings reported when the composite fails to beat a
single-domain baseline, the replayable archive that lets the whole evaluation
re-run without re-fetching, and the honest treatment of the literature's
critiques of the feeds themselves. Any one of those is the substance; the
engineering is the substrate underneath it.

---

## What is claimed, precisely

- **Claimed**: that a multi-modal composite of market, geopolitical and hazard
  signals, weighted by the JRC handbook procedure, discriminates later labelled
  instability better than the best single-domain baseline, by a margin reported
  with confidence intervals. Per-domain subtasks are secondary.
- **Not claimed**: to predict specific events; to outperform established
  forecasting systems; to generalise to feeds it was not evaluated on; that
  live-collected data forms part of the formal evaluation; that the auxiliary
  sentiment signal predicts markets.

Overclaiming would cost more than it bought. The bar above is achievable and it
is this project's own.

---

## Provenance trail

For anyone who wants to check rather than take the above on trust:

- **Code** — `git log --all --pretty=fuller` shows every commit, author and
  date. The system grew a commit at a time and the history says so.
- **Design** — this `docs/architecture/` directory was committed before the
  application code it describes. The specification precedes the implementation
  in the history, which is the opposite of what reverse-engineering looks like.
- **Methodology** — [`../methodology.md`](../methodology.md) Part A was fixed
  before the evaluation harness was written. Later changes are versioned, never
  silently overwritten.
- **Literature** — [`../methodology.md`](../methodology.md) Part B lists what
  was actually read, with citations: the OECD/JRC handbook, the ViEWS
  conflict-forecasting work (Hegre et al., 2019), the CEWS field review (Davies
  et al., 2023). That is the lineage.
- **Decisions** — every scope shift, including the re-anchor from a
  finance-led composite to a multi-modal one, is its own pull request with a
  written rationale. None of it was invented afterwards.

Every section of this specification lives on a branch behind a pull request
rather than as a local draft, and that is why: the trail only works if it was
laid down as the work happened.
