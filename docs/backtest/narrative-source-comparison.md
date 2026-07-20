# Does archive-derived narrative volume track the DOC API series?

**Status: no verdict yet.** The instrument is built and one pass has run, but that
pass compared two quantities that were never the same thing. The corrected run is
blocked on GDELT's rate limiter. This document records what exists, what the first
pass showed, and why its numbers must not be read as an answer.

Issue #557. Depends on #555.

## What is being decided

The lead-time gate's negative result — physical sensor spikes do not precede
narrative spikes at better than chance — was measured against DOC API article
volume. #555 produces daily counts from GDELT's raw export grid instead, which is
what makes anchors older than the DOC API's three-month window scorable.

Before any gate result rests on the archive series, the two have to be shown to
measure the same thing. If they do not, the archive does not extend the existing
result backwards; it only baselines a new one.

## How it is measured

`app/backtest/source_compare.py` reports two numbers per country:

- **Spearman** on the daily series. The archive counts mentions in the thousands
  where the DOC API counts articles in the tens, so only the ordering is
  comparable and a rank correlation is the honest measure.
- **Spike-day agreement** — the day each series first crosses `TAU_N`, found with
  the gate's own log scaling, rolling window and threshold.

The second is the one that matters. The gate does not consume volume; it consumes
`detect_lead`'s first narrative spike. Two series can correlate at 0.95 and still
disagree about the only day the gate reads.

## Why the first pass does not answer the question

The DOC side used the gate's existing query, `sourcecountry:<name>` — articles
**published by** that country's outlets, on any subject. The archive side counts
`ActionGeo` — events **located in** that country, reported by anyone in the world.

Those are different measurements. Japanese coverage of a Peruvian earthquake counts
toward Peru in the archive series and toward Japan in the DOC series. Disagreement
between them is expected and says nothing about whether the archive can stand in.

The like-for-like DOC scope is `locationcc:<FIPS>`, articles **about** places in the
country. `scripts/compare_narrative_sources.py --scope location` is now the default
and is what the real run must use.

## First pass, for the record only

2026-04-20 .. 2026-07-19, 91 days, 15 registry countries, DOC scope
`sourcecountry`. **These numbers answer the wrong question.**

| country | measure | spearman | DOC spike | archive spike | gap |
|---|---|---:|---|---|---:|
| AF | mentions | 0.098 | 2026-05-26 | 2026-06-09 | 14 |
| AF | events | 0.072 | 2026-05-26 | 2026-06-09 | 14 |
| CL | mentions | 0.538 | 2026-06-04 | 2026-06-26 | 22 |
| CL | events | 0.484 | 2026-06-04 | 2026-06-26 | 22 |
| CN | mentions | 0.549 | 2026-05-27 | 2026-07-17 | 51 |
| CN | events | 0.524 | 2026-05-27 | 2026-07-17 | 51 |
| MX | mentions | 0.682 | 2026-05-27 | 2026-06-11 | 15 |
| MX | events | 0.667 | 2026-05-27 | 2026-07-10 | 44 |
| PE | mentions | 0.386 | 2026-06-04 | 2026-05-22 | −13 |
| PE | events | 0.380 | 2026-06-04 | 2026-05-22 | −13 |
| PH | mentions | 0.711 | none | none | n/a |
| PH | events | 0.687 | none | none | n/a |
| RU | mentions | 0.563 | 2026-05-28 | 2026-05-20 | −8 |
| RU | events | 0.572 | 2026-05-28 | 2026-05-29 | 1 |

Eight of fifteen countries produced nothing: CU, ID, IT, JP, VE and VU returned
HTTP 429, and NZ and PG returned an empty DOC window.

Summary as measured: median Spearman 0.549 (mentions) and 0.524 (events) over
seven countries; both sources spiked in six; **the same spike day in zero**; median
absolute gap 15 days (mentions), 22 days (events).

## What blocks the corrected run

Rate limiting, the problem #550 §1.2 already describes. The DOC client honours the
published one-call-per-five-seconds, but the limiter punishes burst volume across a
longer window: fifteen paced calls tripped it, and a single probe minutes later was
still refused. Responses are cached, so a re-run resumes rather than repeating.

Two options, neither tested: raise the inter-call interval well above five seconds
for this script specifically, or fetch on a slow schedule and let the cache fill
across several passes.

## What has to happen next

1. Re-run with `--scope location` once the limiter clears, covering enough countries
   to say something. Seven of fifteen is too thin regardless of scope.
2. Report Spearman and spike-day agreement per country, and pick `mentions` or
   `events`.
3. State a verdict: may the archive series stand in for the DOC series, or does it
   only baseline a new gate?

A negative answer remains a perfectly good outcome, and should be recorded as one.
