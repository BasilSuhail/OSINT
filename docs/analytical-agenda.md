# Analytical Agenda — What We Do With the Data

> **Tracking issue:** the pinned "North star: analytical agenda" issue mirrors this document
> in plain language and carries the live workstream checklist. This document is the canonical
> technical record; the issue is the trail.

This document answers the critical-analysis questions — the professor's questions — one by one.
The rule for every answer: **it must be a measurable statistic, not "use AI"**. Every claim below
is something we can compute, validate, and be wrong about.

Roughly half of the questions are already answered rigorously by
[`methodology.md`](methodology.md) (pre-registered evaluation, AUROC/AUPR/Brier, nine baselines,
lead-time analysis, JRC-style sensitivity analysis). This document maps each question either to
the exact section that answers it, or to a new planned workstream.

---

## Quick navigation

- [Summary table](#summary-table)
- [Q1 — Story similarity](#q1--two-articles-report-the-same-thing--same-story-or-different)
- [Q2 — Perspective divergence](#q2--different-countriesoutlets-see-the-same-event-differently--use-that-variance)
- [Q3 — True vs false](#q3--true-vs-false-information-corroboration-not-a-truth-oracle)
- [Q4 — Score composition & bias](#q4--what-makes-up-the-score-and-what-biases-are-in-it)
- [Q5 — Validation & prediction](#q5--how-do-we-validate-how-do-we-predict-instead-of-post-process)
- [Q6 — Which number matters](#q6--which-number-on-the-dashboard-matters-most)
- [Q7 — Crops, water, food, disease](#q7--predict-events-affecting-cropswaterfooddisease)
- [Workstreams](#workstreams)

---

## Summary table

| # | Question | Method (one line) | Status |
|---|----------|-------------------|--------|
| Q1 | Are two articles the same story? | Sentence-embedding similarity → story clusters | ✅ WS-A live (#297; threshold audited #335) |
| Q2 | Outlets/countries disagree — use it? | Inter-source disagreement index per story; test as leading signal | ⏳ WS-B queued after WS-C |
| Q3 | True vs false? | Corroboration score: independent sources × reliability prior × sensor confirmation | 🔨 WS-C step 2 of 5 (#356) |
| Q4 | What's in the score; what biases? | ✅ [methodology.md Step 9](methodology.md#step-9--sensitivity--robustness) + coverage-bias table | ✅ + ✅ WS-D live (#291) |
| Q5 | Validate? Predict, not post-process? | ✅ Pre-registered backtest ([Steps 3–6](methodology.md#step-3--time-period--data-split)) + forward prediction journal | ✅ + ✅ WS-E live (#293) |
| Q6 | Which number matters most? | Per-indicator univariate AUROC vs ground truth, ranked | ✅ WS-F ranked (#376, `make indicator-ranking`) |
| Q7 | Predict crops/water/food/disease? | New domains, gated behind the Phase-1 #250 gate | 🔭 future |

Legend: ✅ done/live · 🔨 in progress · ⏳ queued or unblocked, not started · 🔭 future, explicitly out of scope now.

---

## Q1 — "Two articles report the same thing — same story or different?"

**Why.** 25 RSS outlets (`app/sources/rss_feeds.json`) means one real-world event arrives many
times in different words. Until the system can say "these are one story", every event count is
inflated by syndication, and outlet-vs-outlet comparison (Q2) is impossible. Story identity is
the foundation for Q2 and Q3.

**What.** *Story clusters*: one row per real-world story, carrying the set of member articles
and the count of independent outlets that told it.

**Where.** ✅ Delivered as workstream **WS-A** (#296/#297): `app/stories/` — pure clustering
layer + 30-minute beat task + `make stories`; `stories` / `story_members` tables. Since
#355/#356 each story also carries `owner_count` (distinct content owners, not feeds). Related
paused work: #126 (BERT sentiment,
[`architecture/CII-METHODOLOGY.md`](architecture/CII-METHODOLOGY.md)) and #155 (distilbert-ONNX
swap, [`architecture/ENRICHMENT-METHODOLOGY.md`](architecture/ENRICHMENT-METHODOLOGY.md)).

**How.** As built: TF-IDF vectors over headline tokens, cosine similarity, greedy leader
clustering at a 0.35 join threshold — assignments append-only over a rolling 72 h window.
(The original plan reached for sentence embeddings; TF-IDF proved sufficient at audit and
stays cheap on the Pi. An embedding upgrade remains open as a new `stories-v2` method version
if audit quality ever degrades.) Evaluation: the #334/#335 hand-audit of ~30 stratified
clusters confirmed the threshold — verdicts committed in
[`audits/stories-threshold-audit.md`](audits/stories-threshold-audit.md).

**Thesis claim it supports.** "The system measures event salience by *independent corroboration
count*, not raw article volume."

---

## Q2 — "Different countries/outlets see the same event differently — use that variance"

**Why.** This is the most original idea on the list. When outlets from different countries
describe the same physical event in sharply different tones, that disagreement is not noise —
it is a candidate *leading indicator*: contested narratives precede contested situations.

**What.** An **inter-source disagreement index** per story cluster: the dispersion (std or IQR)
of tone across outlet-origin groups. Then the testable hypothesis: *narrative divergence on the
same physical event spikes before ACLED-confirmed instability* — testable with exactly the
lead-time machinery built for #250.

**Where.** New workstream **WS-B**, depends on WS-A story clusters.
Concrete prerequisite (verified): `app/sources/rss_feeds.json` has per-outlet identity but **no
outlet-origin-country field** — `default_country` is the *coverage* default (null for e.g. BBC
World), not the outlet's origin. WS-B step one is a static outlet → origin-country mapping.
Tone scoring reuses the existing sentiment enrichment (`app/enrichment/sentiment.py`, VADER
today, #155 upgrade path).

**How.** Within each story cluster: group articles by outlet origin country/bloc → per-group
mean tone → disagreement index = dispersion across groups. This is the Ground News model
(left/center/right spread) generalised to source-country blocs. As a time series per country,
feed it through the existing rolling z-score divergence engine
(`app/divergence/scoring.py`, 30-day baseline in `app/divergence/config.py`) and test lead time
against ground truth exactly as [methodology.md Step 7](methodology.md#step-7--detection-delay-analysis)
prescribes.

**Thesis claim it supports.** "Cross-source narrative divergence is an early-warning signal in
its own right, measurable without access to any proprietary data."

---

## Q3 — "True vs false information" (corroboration, not a truth oracle)

**Why.** No system computes truth, and claiming otherwise fails the defence. What we *can*
compute — honestly and reproducibly — is **corroboration**. And this system has an angle nobody
else has: physical sensors in the same pipeline as the news.

**What.** A per-story **confidence score** with a visible evidence trail, built from three
measurable components:

1. **Independent source count** — outlets in the story cluster, discounted for shared ownership
   / syndication (dedup by owner).
2. **Source-reliability prior** — a static tier list per outlet to start, updated empirically
   later (an outlet's historical corroboration rate becomes its prior).
3. **Physical-sensor confirmation** — does USGS / FIRMS / GDACS geometry corroborate the
   narrative claim in space and time?

**Where.** New workstream **WS-C**, depends on WS-A. The sensor-vs-narrative alignment
machinery already exists from the Phase-1 gate work
(#250, [`architecture/06-validation.md`](architecture/06-validation.md), `app/backtest/`).

**How.** Score = f(independent count, reliability prior, sensor match). Never a bare
true/false verdict — always the score plus its three inputs, so an analyst can disagree with
the weighting. Calibration check: does the score's implied probability match observed
confirmation rates (reliability diagram, same toolkit as
[methodology.md Step 6](methodology.md#step-6--metrics))?

**Progress (the 5-step plan, sequenced on #282).**

1. ✅ **Threshold audit** (#334/#335) — 30 clusters hand-checked against the 0.35 similarity
   threshold before anything was built on top; verdicts in
   [`audits/stories-threshold-audit.md`](audits/stories-threshold-audit.md); 0.35 confirmed.
2. ✅ **Outlet independence registry** (#355/#356) — `owner` + `syndication` fields in
   `rss_feeds.json`; `stories.owner_count` counts distinct content owners (BBC's two feeds are
   one owner, RT + TASS one state controller, the Yahoo-hosted feed counts as Reuters wire).
3. 🔨 **Sensor cross-check rules** — declared per claim type, mechanical, no tuning:
   earthquake → USGS row in window/geography, wildfire → FIRMS, disaster → GDACS, market crash
   → market drawdown; each rule returns confirmed / unconfirmed / not-applicable.
4. ⏳ **The score** — `corroboration = f(independent_owners, sensor_confirmations)`, formula
   fixed and versioned (`corroboration-v1.0`) *before* looking at how scores distribute.
5. ⏳ **Surface it** — score on the /stories card + API; the `N src` badge becomes an honest
   confidence signal.

**Thesis claim it supports.** "Cross-checking narrative claims against physical-sensor data
yields a corroboration signal unavailable to news-only systems."

---

## Q4 — "What makes up the score, and what biases are in it?"

**Why.** A composite index nobody can decompose is a black box, and black boxes fail review.

**What / Where — mostly answered already.** The composite follows the JRC handbook design and
its bias analysis is pre-specified in
[methodology.md Step 9 — Sensitivity & robustness](methodology.md#step-9--sensitivity--robustness):
weight Monte-Carlo, normalisation alternatives, per-source ablation, country-level LOOCV.
Ground-truth composition is [Step 2](methodology.md#step-2--ground-truth-hybrid-multi-modal).
The dashboard side ("show why a score moved") is project-direction §9's inspectability goal.

**New: coverage-bias quantification (WS-D).** Media attention per country is wildly uneven —
GDELT's known coverage bias is acknowledged in
[methodology.md B.3](methodology.md#b3--event-data-sources-and-their-limits) but not yet
*measured* in our own data.

**How (WS-D).** Normalise per-country event counts against that country's own rolling baseline
rather than against other countries — the per-entity rolling z-score machinery in
`app/divergence/scoring.py` does exactly this pattern already. Publish a per-country
coverage-bias table (observed volume vs baseline, by source), so every score can be read
alongside how over- or under-covered that country is.

**Thesis claim it supports.** "Every component, weight, and known bias of the composite is
quantified and published — the index is auditable end to end."

---

## Q5 — "How do we validate? How do we predict instead of post-process?"

**Why.** "The dashboard showed it after it happened" is reporting. A thesis needs forecasting
with a scoreboard.

**What / Where — backtest half exists.** Pre-registered protocol
([methodology.md Steps 3–6](methodology.md#step-3--time-period--data-split)): train/validation/test
split by time, prediction task definition, nine baselines, AUROC/AUPR/Brier. The #250 Phase-1
lead-time gate engine is implemented (`app/backtest/`,
[`backtest/issue-250-closeout.md`](backtest/issue-250-closeout.md) — final report artifact
pending a DB dry-run).

**New: forward prediction journal (WS-E).** Every threshold-breach warning the *live* system
emits gets logged — timestamp, country, score, horizon — before the outcome is known, then
graded against ground truth once the horizon passes. Report the Brier score of our own live
forecasts, accumulating over time.

**How.** One table (predictions journal) + one recurring grading job + one accumulating
scorecard. Cheapest, highest-thesis-value item on this list: it converts the dashboard into a
forecasting system with an auditable track record, and it is immune to the hindsight bias that
[methodology.md Step 1](methodology.md#step-1--why-pre-register) warns about — the journal
*is* pre-registration, continuously.

**Thesis claim it supports.** "The system's live forecasts have a measured, timestamped track
record — not a retrospective narrative."

---

## Q6 — "Which number on the dashboard matters most?"

**Why.** If everything is highlighted, nothing is. Prominence should be earned by measured
predictive value, not aesthetics.

**What.** A per-indicator **information value**: how well each individual signal, alone,
anticipates ground-truth instability.

**Where.** New workstream **WS-F**. The computation piggybacks on the existing backtest
registry (`app/backtest/registry.py`) — the single-domain baselines in
[methodology.md Step 5](methodology.md#step-5--baselines) are already per-indicator models in
miniature. Dashboard reordering is later frontend work, out of scope for WS-F itself.

**How.** Univariate AUROC (or mutual information) per indicator against the ground-truth
labels, ranked. Publish the ranking; the dashboard eventually orders panels by it.

**Thesis claim it supports.** "Indicator prominence is empirically justified — the system knows
which of its own numbers carry signal."

---

## Q7 — "Predict events affecting crops/water/food/disease"

**Why.** Highest-impact prediction targets — and entirely new *domains*, each with new data
sources (FAO food security, disease surveillance feeds) and new ground-truth problems.

**What / Where / How.** Deliberately **out of scope** until the Phase-1 gate (#250) produces
its final report artifact and passes. Recorded here so the intention is not lost and so it
cannot creep in early. When the gate passes, each domain enters as a new evidence stream
through the same fetcher contract ([`architecture/03-ingestion.md`](architecture/03-ingestion.md))
and is evaluated under the same pre-registered protocol before any claim is made.

---

## Workstreams

Each workstream becomes its own issue → branch → PR when it starts (1:1:1 flow). Letters, not
numbers — the numeric "WS1…" series is already used by the console-theme effort.

| WS | Name | Depends on | One-line scope | Status |
|----|------|------------|----------------|--------|
| WS-A | Story clustering | — | TF-IDF + greedy leader clustering of articles into stories | ✅ live — #296/#297, threshold audit #334/#335, 30-min beat, `make stories` |
| WS-B | Disagreement index | WS-A | Outlet-origin mapping + per-story tone dispersion + lead-time test | ⏳ queued after WS-C |
| WS-C | Corroboration score | WS-A | Independent-owner count × reliability prior × sensor confirmation | 🔨 step 2 of 5 — audit #335, owner registry #356 |
| WS-D | Coverage-bias table | — | Per-country volume vs own rolling baseline, published | ✅ live — #290/#291, `make coverage`, /coverage card |
| WS-E | Prediction journal | — | Log live warnings, grade later, accumulate a Brier scorecard | ✅ live — #292/#293, daily beat, `make journal`, /scoreboard card |
| WS-F | Indicator value ranking | — | Univariate AUROC per indicator vs ground truth, ranked | ✅ ranked — #376, `make indicator-ranking`; |hazard z| leads (~0.59), magnitude variants dominate raw |
| WS-G | Local LLM validator | WS-A + WS-C substrate | Ollama claim extraction, contradiction detection, cluster QA — with a measured error rate | 💡 planned (plan on #282) |

```
WS-A ──► WS-B ──┐
  └────► WS-C ──┴──► WS-G          WS-D   WS-E   WS-F   (independent)

#250 gate report ──gates──► Q7 (food / water / disease domains)
```

**WS-G guardrails (non-negotiable, from the #282 plan).** The local model (Ollama over
localhost HTTP, nothing leaves the machine) is *another noisy annotator*, never ground truth:
its output is stored with `model + prompt` as a method_version, its agreement with a
human-checked sample (~50 items) is measured before anything downstream consumes it, and its
disagreement rate is published like any other error rate. It assists WS-C (structured claims
for the sensor rules) and WS-B (facts-vs-framing disagreement typing) *alongside* the
mechanical rules, never instead of them.

**The GDELT backfill and the fair test (the board's third ✅ row).** The composite's third
domain landed via bulk-file backfill (#330/#331): 11 years of daily GDELT files → 30,974
country-month Goldstein means through the unchanged v1.0 pipeline, composite coverage of the
eval panel 18% → 99%. The pre-registered three-domain test then ran: AUROC ~0.502 vs a 0.929
per-country base rate — a coin flip on the *incidence* target, published honestly. Reading: the
composite z-scores each country against its own past, so it is an **onset/escalation**
instrument being graded on an incidence exam; the next evaluation (pre-registered before
running) restricts scoring to onset months. Full trail on #282.

Delivery order now: WS-C steps 3–5 → WS-B → WS-G, with WS-F free to run whenever backtest
bandwidth allows.
