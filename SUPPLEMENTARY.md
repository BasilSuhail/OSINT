# Supplementary material

Everything produced by the work that does not belong in the main text: the
dataset, the full result tables, the hand-checked audit sheets, and the
annotated code behind each method.

Nothing here re-explains method choices — that argument belongs in the main
document. This is the evidence that the work was done, in a form a reader can
open, run and check.

## What you have been given

| | |
| --- | --- |
| This document | Eight appendices, each pointing at files below |
| `results/data/` | The analysis panel (31,637 rows) and the coverage table, as CSV |
| `results/reports/` | Nine result sets, each as machine-readable JSON and a rendered table |
| `results/audit-sheets/` | Four sheets a person filled in by hand |

Everything else — the running system, its console, its operational detail —
lives in the repository and is not needed to read this:
**<https://github.com/BasilSuhail/OSINT>**

Code references below are links into that repository. The `results/` files
travel with this document and open without it.

## How the implementation was produced

The code in this repository was written with heavy assistance from a large
language model, used as a coding tool throughout.

What that assistance did **not** decide is the part this document is evidence
for: which methods to use, what each threshold should be, what counts as a
positive label, which baselines a result must beat, when a protocol is frozen,
and whether a result is reported as a success or a failure. Those choices are
recorded here with the measurement that drove each one — including the ten in
Appendix H that ended a chosen approach.

Every method carries a frozen version string, every result is regenerable from
the commands listed beside it, and every figure states the date it was measured.
The intention is that nothing in this document has to be taken on trust.

---

## Contents

| Appendix | What is in it |
| --- | --- |
| [A — The dataset](#appendix-a--the-dataset) | The analysis panel, its schema, how to open it |
| [B — Results](#appendix-b--results) | Every result file, with the headline tables reproduced |
| [C — Data cleaning and validation](#appendix-c--data-cleaning-and-validation) | Annotated code for every rule that rejects or repairs a row |
| [D — Natural language processing](#appendix-d--natural-language-processing) | Vectorisation, word embeddings, translation, classification — annotated |
| [E — Database design](#appendix-e--database-design) | Tables, keys, relationships, and the storage rules |
| [F — Bias measurements](#appendix-f--bias-measurements) | The measured composition of every input |
| [G — Human audit sheets](#appendix-g--human-audit-sheets) | The rows a person checked by hand, and the agreement they produced |
| [H — What was tried and rejected](#appendix-h--what-was-tried-and-rejected) | Approaches abandoned, and the measurement that ended each one |

Every file referenced is in [`results/`](results/) and every path links to the
code that produced it.

---

# Appendix A — The dataset

## A.1 The analysis panel

**[`results/data/panel.csv`](results/data/panel.csv)** — 2.3 MB, one row per
country-month.

| Property | Value |
| --- | ---: |
| Rows | 31,637 |
| Countries | 200 |
| Span | 1996-12 → 2026-06 |
| Positive `label_any` | 7,088 |
| Rows carrying a composite score | 17,367 |

Built by [`app/panel/run.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/panel/run.py); metadata in
[`results/data/panel-meta.json`](results/data/panel-meta.json). CSV only — a
Parquet copy was described here before one existed, and the claim is removed
rather than left standing.

### Schema

| Column | Type | Meaning |
| --- | --- | --- |
| `country` | ISO-2 | The unit of observation |
| `month` | timestamp | Month start, UTC |
| `label_p1` | 0/1 | Armed conflict onset that month |
| `label_p2` | 0/1 | Mass protest escalation |
| `label_p3` | 0/1 | State-based violence intensification |
| `label_any` | 0/1 | Union of the three — the primary target |
| `magnitude_p1..p3` | int, nullable | Event magnitude behind each label |
| `signal_market` | float | Market-domain z-score, within country |
| `signal_geopolitical` | float | Geopolitical z-score, within country |
| `signal_hazard` | float | Hazard z-score, within country |
| `composite_score` | float ∈ [0,1] | The combined index |
| `method_version` | string | Frozen method identifier |

### Opening it

```python
import pandas as pd
panel = pd.read_csv("results/data/panel.csv", parse_dates=["month"])

panel.groupby("country")["label_any"].mean().sort_values(ascending=False).head(10)
panel[["signal_market", "signal_geopolitical", "signal_hazard"]].describe()
panel.groupby(panel.month.dt.year)["label_any"].mean()
```

### The shape of the target, and why it matters

The positive rate is **26.53%** on the training span and **21.83%** on the
held-out span — but it is not spread evenly. Of the **197** countries the panel
carries between 2015-01 and 2022-12, **91 are never labelled** and **16 are
labelled in at least 90% of their months**. That is **107 of 197, or 54%,
constant either way.** Over the whole span the same count is 80 never, 11
always, 91 of 200.

An earlier revision of this appendix gave 238, 133 and 10 here. Those figures
counted countries in the label source rather than rows in the panel, which is a
different population from the one every result is computed on. The numbers
above are recomputed from `panel.csv` itself with the snippet below.

That single fact is why a pooled metric over this panel is misleading, and it
is visible directly in the CSV:

```python
rate = panel.groupby("country")["label_any"].mean()
(rate == 0).sum(), (rate >= 0.9).sum()
```

## A.2 The coverage table

**[`results/data/coverage-bias.csv`](results/data/coverage-bias.csv)** —
per-country attention baselines over the label source.

| Property | Value |
| --- | ---: |
| Countries | 200 |
| Total events measured | 3,080,334 |
| Share held by the top 5 | 30.25% |
| Share held by the top 10 | 47.68% |
| Share held by the top 20 | 65.28% |

Columns: `country`, `coverage_months`, `observed_months`, `total_events`,
`events_per_month`, `global_share`, `fatalities_per_event`, `baseline_std`.

Produced by [`app/coverage/run.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/coverage/run.py).

## A.3 Redistribution note

These are **derived aggregates** — monthly indicators, z-scores, binary labels
and country-level summary statistics computed by this project. No upstream
provider's rows are reproduced. Anyone re-running the pipeline fetches the
source data themselves, under their own agreement with each provider; see
[`NOTICE.md`](https://github.com/BasilSuhail/OSINT/blob/main/NOTICE.md).

---

# Appendix B — Results

Every file below is machine-generated and regenerable. The `.md` is a rendered
view of the `.json` beside it; the JSON is the artefact of record.

| Result | Files | Produced by |
| --- | --- | --- |
| Baseline head-to-head | [`baselines-report.json`](results/reports/baselines-report.json) · [`.md`](results/reports/baselines-report.md) | `make baselines` |
| Onset evaluation | [`onset-eval-report.json`](results/reports/onset-eval-report.json) · [`.md`](results/reports/onset-eval-report.md) | `make onset-eval` |
| Within-country evaluation | [`within-country-eval.json`](results/reports/within-country-eval.json) · [`.md`](results/reports/within-country-eval.md) | `make within-eval` |
| Indicator ranking | [`indicator-ranking.json`](results/reports/indicator-ranking.json) · [`.md`](results/reports/indicator-ranking.md) | `make indicator-ranking` |
| Narrative divergence | [`disagreement-report.json`](results/reports/disagreement-report.json) · [`.md`](results/reports/disagreement-report.md) | `make disagreement` |
| Sensor cross-checks | [`sensor-checks-report.json`](results/reports/sensor-checks-report.json) · [`.md`](results/reports/sensor-checks-report.md) | `make sensor-checks` |
| Story clustering | [`stories-report.json`](results/reports/stories-report.json) · [`.md`](results/reports/stories-report.md) | `make stories` |
| Claim validator | [`validator-report.json`](results/reports/validator-report.json) · [`.md`](results/reports/validator-report.md) | `make validator` |
| Forward prediction journal | [`prediction-journal.json`](results/reports/prediction-journal.json) · [`.md`](results/reports/prediction-journal.md) | `make journal` |

## B.1 The head-to-head, both windows

The declared bar: the composite must strictly dominate each single-domain
baseline on **AUROC and AUPR**. Strict common support; seed 20260703.

Training span 2015-01 → 2022-12, k = 1, n = 12,618, positive rate 0.2599:

| Contender | AUROC | AUPR | Brier |
| --- | ---: | ---: | ---: |
| B0 random | 0.5040 | 0.2624 | 0.3301 |
| B1 persistence | 0.8697 | 0.7250 | 0.0999 |
| B2 base rate | **0.9290** | **0.8346** | 0.0962 |
| B3 geopolitical only | 0.5029 | 0.2619 | 2.0893 |
| B4 market only | 0.4930 | 0.2929 | 0.3982 |
| B5 hazard only | 0.4794 | 0.2755 | 0.6281 |
| **B6 composite** | **0.5016** | **0.2741** | 0.2605 |

Held-out span 2023-01 → 2024-12, opened 2026-08-10, k = 1, n = 4,593,
positive rate 0.2151:

| Contender | AUROC | AUPR | Brier |
| --- | ---: | ---: | ---: |
| B0 random | 0.5032 | 0.2207 | 0.3295 |
| B1 persistence | 0.8895 | 0.7478 | 0.0742 |
| B2 base rate | **0.9495** | **0.8413** | 0.0731 |
| B3 geopolitical only | 0.5060 | 0.2249 | 1.8270 |
| B4 market only | 0.4950 | 0.2533 | 0.2815 |
| B5 hazard only | 0.4778 | 0.2411 | 0.7069 |
| **B6 composite** | **0.4983** | **0.2351** | 0.2618 |

Machine verdict, identical at every horizon in both windows:

```json
{"passed": false, "beaten": [],
 "lost_to": ["B3 geopolitical only", "B4 market only", "B5 hazard only"],
 "summary": "FAIL — the composite does not beat B3, B4, B5"}
```

Two things a reader should not skim past. **B3's Brier exceeds 1.0** — a Brier
score is bounded by 1 for genuine probabilities, so those values are direct
evidence the single-domain scores are not probabilities and that column is
meaningless for them. And **B2 reaching 0.9495 is not a rival worth admiring**:
it predicts each country's own history, which is what a 0.93 base rate rewards.

## B.2 Within-country concordance, with uncertainty

Pairs drawn within a single country; 1,000 bootstrap resamples **over
countries**, because the country is the unit of independence.

```text
Within-country concordance | 12-month calm | 1,000 bootstrap resamples
                     0.10      0.30          0.50 │ 0.55       0.70
                       |---------|-------------|--┼--|-----------|
  k=1  B0 random             [-----------*----|----:]           0.449
       B1 persistence               [-*---]:                    0.502
       B2 base rate   [-----------*-------------] │    :        0.304
     > B6 composite         [-----------*|----:------]          0.489
  k=3  B0 random             [------*--|---]:                   0.470
       B1 persistence               [-*--] :                    0.501
       B2 base rate   [------------*-------------] │    :       0.302
     > B6 composite           [------|-*--:---]                 0.516
  k=6  B0 random             [-----*---|-]  :                   0.460
       B1 persistence               [-|*-] :                    0.506
       B2 base rate  [-------------*--------------] │   :       0.286
     > B6 composite            [--|--*-:--]                     0.531

  * point estimate   [---] 95% bootstrap CI   > the contender under test
```

Best composite result **0.531** at k = 6, CI **[0.474, 0.582]**. The declared
threshold was 0.55 with a CI excluding 0.5. **Neither condition met at any
horizon.** Verdict computed by `_verdict()`, not by reading the table.

One result the protocol did not anticipate: B2 did not merely collapse toward
0.5, it **inverted** — 0.286 to 0.324 across every cell, consistently below
chance. No mechanism is asserted. It is recorded because suppressing it would
be selective reporting.

## B.3 Forward predictions

**[`results/reports/prediction-journal.json`](results/reports/prediction-journal.json)**

| Source | Method version | Issued | Graded |
| --- | --- | ---: | ---: |
| composite | v1.0 | 501 | **0** |
| composite | v3.0 | 1,035 | **0** |
| disagreement | disagreement-v1.0 | 159 | **0** |
| **Total** | | **1,695** | **0** |

The forward journal is the only out-of-sample evidence available and it has
produced no graded result yet. Every prediction is still pending. Stated
plainly so nobody mistakes an empty column for a favourable one.

---

# Appendix C — Data cleaning and validation

Every rule that rejects, repairs or de-duplicates a row, with the code that
does it.

## C.1 Rejection at write time

A row that asserts something happened must be able to say *what*. Rows with no
readable claim are excluded from the default response rather than deleted, and
remain reachable with `readable_only=false`:

```python
# app/api.py — events()
if readable_only:
    stmt = stmt.where(has_readable_claim())
```

## C.2 Deduplication by stable identity

Upsert on a stable per-source identity, so re-fetching the same window cannot
create duplicates and a corrected upstream row updates rather than doubles:

```python
# app/persistence.py
ENRICHMENT_PAYLOAD_KEYS: Final = (
    "footprint_geojson",      # real hazard geometry, written after ingestion
    "footprint_checked_at",   # cooldown for hazards with no upstream geometry
    ...
)
```

Enrichment keys are listed explicitly because a snapshot refresh must never
overwrite work that was computed after ingestion. Without that list, every
refresh silently discarded the geometry, place resolution and scores attached
to a row.

## C.3 Outcome classification, not success/failure

A fetch that returns HTTP 200 and produces no usable row is **not** a success.
Recording it as one is how a dead feed looks healthy for weeks:

```python
# app/tasks.py — _record_outcome()
if result.state in ("new_data", "unchanged"):
    row.success_n = (row.success_n or 0) + 1
elif result.state == "empty":
    row.empty_n = (row.empty_n or 0) + 1
elif result.state == "misconfigured":
    row.misconfigured_n = (row.misconfigured_n or 0) + 1
elif result.state == "failed":
    row.failure_n = (row.failure_n or 0) + 1
```

## C.4 Cleaning the numeric inputs

Two guards in the normaliser, each protecting against a distinct failure:

```python
# app/composite/normalization.py
MIN_HISTORY: int = 3        # fewer observations → emit 0.0, not a z-score
STD_TOLERANCE: float = 1e-9 # constant history → emit 0.0, not a huge z
```

Without the second, a constant series such as `[0.1] * 12` produces a
sub-1e-15 standard deviation and therefore a meaningless enormous z-score.

## C.5 Refusing to impute

A domain that is absent is excluded and the remaining weights renormalised. It
is **not** entered as zero:

```python
# app/composite/scoring.py
present = {d: w for d, w in weight_dict.items() if d in domain_z}
weight_total = sum(present.values())
if not present or weight_total <= 0.0:
    continue          # no known domain — refuse to compute rather than invent
```

Entering an absent domain as z = 0 asserts "exactly average", which is a
different claim from "we do not know". Every imputed zero pulled the score
toward 0.5, hardest for the countries missing the most data — the quiet ones
the index most needs to separate.

## C.6 Refusing to record a constant as a forecast

A predictor returning the same number for every country is not predicting.
Exact flatness was the original test and the data walked straight through it:
the live score took seven distinct values across 519 rows, **98.8% of them
exactly 0.5**, so `min != max` held and 1,101 forecasts of a constant were
recorded as forecasts. The test is now **concentration** — the share of
observations taking the single most common value
([`app/composite/degeneracy.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/composite/degeneracy.py)).

## C.7 Refusing to grade the past as a forecast

```python
# app/journal/emit.py
if _month_start(score["bucket_start"]) < current_month:
    continue    # window overlaps the known past — grading it fakes a record
```

---

# Appendix D — Natural language processing

Four NLP stages run over the text. Two are classical and deterministic; two use
a local neural model. All four are annotated below.

## D.1 Tokenisation and TF-IDF vectorisation

The clustering and divergence measures share one vectoriser
([`app/stories/vectorize.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/stories/vectorize.py)):

```python
def tokenize(title: str) -> list[str]:
    """Lowercase alphanumeric tokens; stopwords, calendar words and short
    tokens dropped."""

def build_idf(documents) -> dict[str, float]:
    """Smoothed idf: ln(N / df) + 1 over tokenized documents."""

def vectorize(tokens, idf) -> dict[str, float]:
    """tf-idf sparse vector; unseen tokens get idf 1.0 (neutral)."""

def cosine(a, b) -> float:
    """Cosine similarity between sparse vectors; 0.0 when either is empty."""
```

Sparse dictionaries rather than dense matrices, because the vocabulary is the
union of a few thousand headlines and most entries are zero.

**Where it is used.** Story clustering groups articles describing one event.
Narrative divergence measures how differently country blocs word the same
story: build a TF-IDF centroid per outlet-origin country, then take the mean
pairwise cosine distance.

**What it cannot do.** TF-IDF cosine cannot see that *militant* and *fighter*
denote the same person. That substitution is exactly the divergence the measure
is meant to catch, and it is caught only because the surface words differ — not
because the method understands them. This is the ceiling that motivated D.2.

## D.2 Word embeddings — dense semantic retrieval

Where TF-IDF compares words, the embedder compares meaning
([`app/brain/embeddings.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/brain/embeddings.py), `embed-v1.0`):

```python
def story_embed_text(*, title: str, gist: str | None, keywords: list[str]) -> str:
    """One string per story — title, gist and top member keywords — so a
    story is embedded once rather than per member article."""
```

Each story is embedded once by a small local embedding model and the vector is
stored in `story_embeddings`. Question-time retrieval ranks candidate stories by
cosine similarity against the question's vector, so a question worded nothing
like the headline can still reach it — the case that keyword retrieval fails.

**Design choice worth stating.** Embeddings serve *retrieval*, not *scoring*.
No published number in Appendix B depends on them. A retrieval mistake surfaces
the wrong story to a reader who can see it is wrong; a scoring mistake would
propagate silently into an index.

## D.3 Translation before analysis

Non-English headlines are translated *before* anything reads the words, because
the severity keywords, the geographic resolver and the story tokeniser are all
English. Skipping this was measurable: an Arabic desk resolved **0 of 25 rows**
to a country and produced one constant severity value.

Failure is recorded rather than hidden — verified with the model unreachable:

```python
{'title': 'مرحبا بالعالم',
 'title_translation': {'status': 'failed', 'model': 'llama3.2:3b',
                       'method_version': 'translate.v1.0',
                       'attempted_at': '2026-08-16T18:16:09Z'}}
```

The original is always kept verbatim. A desk that silently stopped translating
is visible in the data rather than merely quiet.

## D.4 Severity classification

Three generations, each replaced for a measured reason:

| Version | Method | Why replaced |
| --- | --- | --- |
| v1 | six-keyword substring match | `Workers strike over pay` and `50 killed in market bombing` scored identically; `crash` matched a car, a share index and an aircraft. Produced **42 of 50** findings in the source audit |
| `keyword-v2` | graded rule — fatal / violent / disruptive / none | Discriminates better, still a word rule. **Retained** as the instant fallback at ingest so a model outage cannot stall the pipeline |
| LLM grading | local model reads the headline, returns a score **and a written reason** | Current. Measured **0.860 agreement** with a human rater, 0 floor violations. Five smaller models tested against the same rater; none matched |

The written reason is the point: a number nobody can interrogate is the failure
this layer exists to prevent.

**Honest limits.** 0.860 is agreement with *one* rater and is **not
chance-corrected** — no kappa has been computed, and on a three-level scale a
share of that agreement is chance. Inter-rater reliability across several raters
has not been measured. The audit sheet is in Appendix G.

## D.5 What is not used

**Knowledge graphs — not attempted.** Entity-relationship extraction across
articles would be the natural next step for linking a concept in one story to
the same concept in another. Story clustering currently does that job at the
document level rather than the entity level. Recorded as an option not taken,
not as a gap that was missed.

**Sentiment as a scored input — deliberately excluded.** Sentiment is computed
and displayed, and it is not permitted into any published index. It is a noisy
annotator over headlines, and the composite already has enough unvalidated
inputs.

---

# Appendix E — Database design

One PostgreSQL instance, one schema, no sharding. Every table below is created
by an Alembic migration in [`migrations/`](https://github.com/BasilSuhail/OSINT/tree/main/migrations/); the ORM definitions
are in [`app/db_models.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/db_models.py).

## E.1 The core

```
                    ┌──────────────┐
                    │    events    │  canonical row from any source
                    │──────────────│  PK id
                    │ source       │  UNIQUE (source, source_event_id)
                    │ occurred_at  │  ← when it happened
                    │ fetched_at   │  ← when we saw it   (both kept: the gap
                    │ country      │     is reporting delay, and it matters)
                    │ lat / lon    │  nullable — unknown is a valid answer
                    │ severity     │  source-relative, never cross-comparable
                    │ payload      │  JSONB — source-specific detail
                    └──────┬───────┘
                           │
          ┌────────────────┼───────────────────┐
          │                │                   │
   ┌──────▼──────┐  ┌──────▼───────┐   ┌───────▼────────┐
   │story_members│  │ composite_   │   │ ingest_health  │
   │ story_id ───┼─┐│  signals     │   │ per source-day │
   │ event_id    │ ││ country      │   │ counters +     │
   └─────────────┘ ││ bucket_start │   │ last state     │
                   ││ domain,value │   └────────────────┘
        ┌──────────▼┴─────┐    │
        │     stories     │    │ monthly aggregate, kept
        │ PK id           │    │ after the events expire
        │ title, last_seen│    ▼
        └────┬─────┬──────┘  ┌──────────┐    ┌─────────────┐
             │     │         │  scores  │───▶│ predictions │
   ┌─────────▼┐ ┌──▼──────┐  │ country  │    │ immutable   │
   │story_    │ │story_   │  │ bucket   │    │ ON CONFLICT │
   │corrobora-│ │disagree-│  │ value    │    │ DO NOTHING  │
   │tion      │ │ment     │  └──────────┘    └─────────────┘
   └──────────┘ └─────────┘        ▲
   ┌──────────┐ ┌─────────┐        │         ┌─────────────┐
   │story_    │ │story_   │        └─────────│   labels    │
   │embeddings│ │gist     │      evaluated   │ ground truth│
   └──────────┘ └─────────┘        against   │ kept apart  │
                                             └─────────────┘
```

## E.2 Why it is shaped this way

**One canonical row shape for every source.** A satellite fire pixel, a market
drawdown and a headline all become one `events` row. Sources differ in what
they carry, so the differences live in a JSONB `payload` rather than in fifteen
source-specific tables. One map query, one retention rule, one index.

**Two timestamps, always.** `occurred_at` is when the world moved;
`fetched_at` is when this system learned of it. Collapsing them into one column
destroys the ability to measure reporting delay, which is a documented bias in
this data.

**Labels are a separate table, never joined into `events`.** Ground truth and
inputs must not share a lineage, or an evaluation silently grades a signal
against itself.

**`composite_signals` exists because retention deletes history.** The events
table holds ~30 days. The rolling z-score needs three prior monthly
observations. Persisting one small aggregate row per country-month-domain — a
few thousand rows a year against a 30 GB cap — lets the analysis outlive the
events it came from.

**`predictions` is append-only.** `ON CONFLICT DO NOTHING` on the forecast key,
so an issued prediction can never be rewritten even if the score is later
revised. That immutability is the journal's entire integrity claim.

## E.3 Retention and size

| Rule | Value |
| --- | --- |
| Default event retention | ~30 days |
| Exempt from pruning | market and disaster-archive rows, whose history cannot be cheaply recreated |
| Pruned by ingest time, not occurrence | one source whose publisher releases old months — pruning by occurrence would delete every row on arrival |
| Hard size cap | `STORAGE_CAP_GB`, default 30 |
| Cap behaviour | delete oldest whole event-days, never below the recent floor, never exempt sources |

Measured live: **3.17 GB, 2,483,259 rows** at 30-day retention.

## E.4 Full table list

| Table | Purpose |
| --- | --- |
| `events` | Canonical source rows |
| `stories`, `story_members` | News clusters and membership |
| `story_corroboration` | Independent-teller confidence and its components |
| `story_disagreement`, `disagreement_pairs` | Narrative divergence, and per-country-pair detail |
| `story_sensor_checks` | Physical-sensor comparisons against claims |
| `story_claims`, `story_reviews` | Extracted claims and their reviews |
| `story_gist`, `story_embeddings` | Summaries and retrieval vectors |
| `composite_signals` | Per country-month-domain aggregates that outlive retention |
| `scores` | Composite and country-index results |
| `labels` | Ground-truth outcome labels |
| `predictions` | Immutable forecasts and later outcomes |
| `ingest_health`, `ingest_failures` | Per-source daily outcome counters and failure detail |
| `dead_letter_queue`, `source_quarantine` | Exhausted work; sources resting after repeated failure |
| `housekeeping_runs` | Retention and cap actions taken |
| `place_lookups` | Cached place resolutions |
| `brain_narrative` | Generated situation summaries |
| `gdelt_daily_volume`, `gdelt_archive_day` | Compact historical aggregates and fetch checkpoints |
| `notifications` | Deduplicated alert sends |

---

# Appendix F — Bias measurements

Measured, not asserted. Reproduce with the commands in each subsection.

## F.1 The news registry

```python
from app.sources.rss_registry import outlet_country_map, content_owner_map
import collections
m, o = outlet_country_map(), content_owner_map()
print(len(m), len(set(m.values())), collections.Counter(m.values()).most_common())
```

| Property | Value |
| --- | ---: |
| Registered feeds | 55 |
| Publishing in English | **54** |
| Publishing in any other language | **1** (Arabic) |
| Distinct outlet-origin countries | 28 |
| Feeds originating in the UK or US | **18 of 55** |
| Distinct content owners | 49 |

Every narrative measurement in this work is computed over that sample. When the
divergence score reports how differently countries word a story, it is in
practice reporting how differently **mostly Anglophone outlets** word it.

## F.2 Row composition — what the database is actually made of

Measured 2026-08-12, 2,259,582 rows:

```text
FIRMS   satellite fire pixels     1,947,913  86.21%  ████████████████████████████████████████████
GDELT   machine-coded events        149,619   6.62%  ███
OPENSKY aircraft positions           82,448   3.65%  ██
NEWS    all 55 RSS feeds             48,289   2.14%  █
ABUSE   cyber indicators             17,104   0.76%  ▍
POLICE  crime records                10,504   0.46%  ▏
OTHER   everything else               3,705   0.16%  ▏
```

**Two automated instruments produce 90% of every row.** The human-written
record — every headline from all 55 feeds — is **2.14%**. A raw row count
measures sensor sampling, not how much happened in the world.

## F.3 One country traced end to end

Iran, measured 2026-08-12 against the live database:

| Property | Value |
| --- | ---: |
| Total stored rows | 19,486 |
| Carrying coordinates | 18,411 (94.5%) |
| Span | 2026-07-13 → 2026-08-12 (the retention window, not the subject's age) |
| Hazard rows | 11,245 (57.7%) |
| Geopolitical rows | 6,877 (35.3%) |
| News rows | 1,334 (6.8%) |
| Distinct news feeds contributing | 35 |
| **Feeds originating in Iran** | **0** |

Ninety-three percent is satellite detections and machine-coded records, not
journalism. The human-written record is 1,334 rows, and **not one of the 35
feeds behind it is Iranian**. No weighting scheme recovers a viewpoint that was
never collected.

For contrast, the historical label panel records 41,630 events for Iran across
127 months — 1.35% of global recorded events, 21st of 200 countries.

**What this supports:** that a set of mostly non-Iranian, almost entirely
English-language outlets published a certain volume; that named blocs worded a
story differently by a measurable amount; that satellites recorded thermal
anomalies at coordinates.

**What it cannot support:** any claim about what is happening inside Iran that
is not visible from outside it, and any reading of low reported volume as low
activity.

---

# Appendix G — Human audit sheets

Model output is not evidence until a person has checked a sample of it. These
are those checks.

| Sheet | What was checked |
| --- | --- |
| [`severity-audit-sheet.md`](results/audit-sheets/severity-audit-sheet.md) | Headlines graded by hand against the model's score and its written reason |
| [`severity-model-bench.md`](results/audit-sheets/severity-model-bench.md) | The same headlines replayed through five candidate models |
| [`validator-audit-sheet.md`](results/audit-sheets/validator-audit-sheet.md) | Extracted claims checked against the article they came from |
| [`stories-audit.md`](results/audit-sheets/stories-audit.md) | Clustering decisions checked by hand — are these articles one story |

The severity sheet is the one that gates a published number: it produced the
**0.860** agreement figure, and it is the reason the model replaced the keyword
rule rather than being trusted on assertion.

**What these sheets do not establish.** Agreement with one rater is not
accuracy, and none of these figures is chance-corrected. A kappa across
multiple raters is the obvious next measurement and has not been taken.

---

# Appendix H — What was tried and rejected

Each entry ended with a measurement, not an opinion.

| Approach | Why it ended |
| --- | --- |
| **Severity by keyword** | A strike and a bombing scored identically; 42 of 50 audit findings traced to one function |
| **Grading conflict by severity** | Escalatory-only filtering meant every stored row scored ≥ 0.700 — mean 0.9863, sd 0.0523 across 168 countries, which z-scores to nothing. Replaced by **log-scaled counts**, sd 0.797, fifteen times the spread |
| **Fire radiative power as hazard severity** | The stored value is detection *confidence*, not intensity — non-monotonic against actual radiative power. Moved to its own domain, aggregated by total FRP |
| **Imputing absent domains as z = 0** | Pulled every score toward 0.5, hardest for the countries with least data — the ones the index most needs to separate |
| **Rebuilding history from the events table** | Retention holds 30 days; the z-score needs 3 monthly observations. 183 of 184 countries sat below the threshold and every live score was exactly 0.5 |
| **Exact flatness as the degeneracy test** | 519 rows, seven distinct values, 98.8% of them 0.5 — `min != max` passed and 1,101 forecasts of a constant were recorded. Replaced by a concentration threshold |
| **Owner count falling back to the source slug** | Read absence of an ownership record as evidence of independence. Ten unrecorded sources would have produced a 0.998 confidence score |
| **Pooled AUROC as the headline metric** | 60% of countries are constants, so it rewarded separating a calm country from a war. Replaced by within-country concordance |
| **One-sided lead-time search** | Searching only backwards makes a positive lead the only possible finding. Replaced by a ±21-day two-sided search |
| **Knowledge-graph entity linking** | Not attempted. Recorded as an option not taken |

---

*Files referenced live in [`results/`](results/). Code paths link to the
repository. Every figure carries the date and the command that produced it.*
