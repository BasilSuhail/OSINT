# Can archive data replace the DOC API as the gate's narrative side?

**Verdict: no, not for the hazard anchors the registry holds.** The DOC API is the
only source that produces a topic-scoped narrative signal dense enough for spike
detection. Its three-month window is therefore a real constraint on the analysis,
not an obstacle that a historical backfill removes.

This contradicts #550 §1.1, which called the GDELT raw historical backfill "the
single largest unlock". The backfill works and is cheap; what it yields is not a
substitute for what the gate reads.

Issues #557 and #555. Depends on #559.

## What the gate actually needs

The gate compares when physical sensors spike against when the narrative spikes.
The narrative side must be:

1. **Topic-scoped.** #528 established that a country's whole news output cannot
   notice one earthquake — an unscoped series is dominated by politics and
   business and never moves for a hazard.
2. **Dense enough to have variance.** `rolling_z` returns 0.0 for a zero-variance
   prior window, so a series that sits at zero most days can never spike however
   large the jump. A thin signal is not a quiet one; it is an undetectable one.
3. **Long enough to reach the anchors.** The registry spans 2026-03-26 to
   2026-07-17, and slow-onset anchors would reach back to 2025.

No single source satisfies all three.

## The three sources, measured

| source | topic-scoped | density | history | verdict |
|---|---|---|---|---|
| DOC API `timelinevolraw` | yes, via query terms | ~800 articles/day per country unscoped; hundreds scoped | ~3 months | **usable, but shallow** |
| GDELT Events export (#555) | **no** — CAMEO codes political actions, there is no earthquake event type | ~5,000 mentions/day per country | years | unlimited but unscopable |
| GDELT GKG export | yes, via themes | **~3 records/day per country** | years | too sparse to spike |

### Events cannot be topic-scoped at all

GDELT's Events export codes political actions. A natural disaster appears only
when someone acts about it. There is no earthquake event type to filter on, so an
Events-derived series is whole-country volume — the exact thing #528 removed.

### GKG is topic-scoped but far too thin

Measured against `jp-20260703-m6.1`, an M6.1 136 km NNE of Hirara. Sampling eight
of each day's 96 files and counting GKG records carrying an earthquake theme whose
locations include Japan:

| day | JP records | global |
|---|---:|---:|
| 2026-07-01 | 2 | 75 |
| 2026-07-02 | 3 | 83 |
| **2026-07-03 (the quake)** | **3** | 106 |
| 2026-07-04 | 1 | 26 |
| 2026-07-05 | 0 | 20 |

Scaling the sample to a full day puts the anchor day at roughly nine records
against six the day before. That is not a spike, and a series moving between zero
and three cannot produce one: the rolling baseline has no variance to standardise
against.

The global column does peak on the anchor day, which is consistent — the event was
covered. It simply is not resolvable at country level in GKG.

GKG is also expensive: 5.5 MB zipped per file against 542 KB for Events, so the
91-day window would cost roughly 48 GB of downloads to produce a series that
cannot spike.

## Which DOC query is comparable — settled along the way

The archive counts `ActionGeo`: events located in a country, reported by anyone.
Three DOC scopes were tried against it.

| query | result |
|---|---|
| `sourcecountry:<name>` | Wrong quantity. Articles **published by** that country's outlets, on any subject |
| `locationcc:<FIPS>` | **Does not exist.** DOC 2.0 has no location operator — that is the GEO API. Verified live: empty window |
| `"<name>"` quoted | Refused: *"The specified phrase is too short."* |
| `<name>` unquoted | **Works** — articles about the country wherever published, 785/day for `peru` |

`--scope mentions` sends the unquoted name and is the default.

Finding this exposed a defect in `narrative._looks_like_error`, fixed alongside: it
matched a blocklist of four known phrases, so unfamiliar prose parsed as a valid
but empty series. "The specified phrase is too short." reached the caller as "no
daily rows parsed", pointing at the window when the query was at fault. It now
recognises the CSV header and reports anything else as what GDELT said.

## Partial comparison results

Four of fifteen countries, 2026-04-20 .. 2026-07-19, `--scope mentions`, before
GDELT's limiter stopped the sweep.

| country | spearman (mentions) | DOC spike | archive spike | gap |
|---|---:|---|---|---:|
| AF | 0.473 | 2026-06-04 | 2026-06-09 | 5 |
| CL | 0.560 | none | 2026-06-26 | n/a |
| CU | 0.528 | 2026-05-20 | 2026-05-20 | **0** |
| ID | 0.542 | 2026-05-21 | 2026-06-03 | 13 |

Three countries with spikes on both sides: one exact agreement, gaps of 5 and 13
days otherwise. Correlations sit near 0.5 — related but not interchangeable.

Completing this sweep is no longer worth the rate-limit budget. Even perfect
agreement on unscoped volume would not make the archive usable, because the gate
needs a *topic-scoped* series and the archive cannot produce one.

## What this means for the analysis

The three-month DOC window is a property of the problem, not a gap to be filled.
Two paths remain open, and neither is the historical backfill:

1. **Accumulate live ingestion.** After three months of running, the DOC window
   covers a usable range of anchors. Calendar-bound, no engineering.
2. **Change the anchor class.** Slow-onset hazards — drought, flood, sustained
   unrest — dominate a country's coverage for weeks rather than hours. An unscoped
   whole-country series may be adequate there precisely because the hazard *is* the
   news, which would make the Events archive usable after all. This is a
   hypothesis, and it is cheap to test: the archive is already ingested for the
   90-day window and #555's ingestion runs at roughly 4 seconds a day.

The second is the more interesting result if it holds, and it inverts the
handover's framing: the anchor class was the constraint all along, not the history.

## What was built and kept

- `app/backtest/gdelt_archive.py` (#555) — daily per-country volume from raw
  exports. Still the right instrument for path 2 above.
- `app/backtest/source_compare.py` (#557) — Spearman plus spike-day agreement,
  using the gate's own scaling and threshold.
- `app/backtest/pacing.py` (#559) — persistent rate-limit pacing, without which
  none of the above measurements survived a second run.
