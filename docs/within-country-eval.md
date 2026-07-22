# The Within-Country Evaluation — pre-registered (#582)

*Declared 2026-07-22, before the evaluation was run. Everything above the
results section was fixed first; the run happened once, after; the results
section quotes that single run. Changes are versioned amendments, never edits —
the same discipline as `docs/onset-eval.md`.*

## Why this exam exists

The composite z-scores each domain **within country** over a rolling window
(`app/composite/normalization.py`), deliberately: it reacts to deviation from a
country's own past, not to an absolute level. Cross-sectional level is removed
by construction.

Both published exams score a single pooled AUROC —
`app/baselines/metrics.py:12` over all rows, `app/onset/run.py:72` over
onset-eligible rows. Nothing in the repo stratifies by country or carries a
country fixed effect.

The panel makes that decisive. Of 238 countries in 2015-2022, **133 are never
labelled** and **10 are labelled in at least 90% of their months**. Sixty
percent of countries are effectively constants, so a pooled metric is largely
rewarded for separating Norway from Syria — a register of known troublemakers,
not a forecast. That is the ~0.93 base rate.

`app/baselines/run.py:158-170` already says this, and proposed the onset exam as
the remedy. That was the right diagnosis, and the onset exam did suppress the
register — but it still scores pooled, and B2 base rate still reaches 0.744 on
it. A country with a violent history remains likelier to onset after twelve calm
months than one without, so the composite is still graded on an axis it cannot
compete on.

This exam asks the question a deviation instrument can answer: **does the
composite rank a country's own onset months above that same country's own calm
months?**

## What this exam is not

It is not a second chance for a failed hypothesis. The pooled results stand as
published. This measures something the pooled exams cannot measure, and its
result is reported whichever way it falls.

It is also not a fix for the input layer. #580's audit shows severity is a two
or three level categorical across nearly every source, and #579 shows the FIRMS
value is the wrong quantity outright. A null here does not distinguish "the
composite construction is wrong" from "the inputs carry nothing" — see
Interpretation below.

## The protocol (fixed)

| element | value |
|---|---|
| onset eligibility | reused unchanged from `app/onset/eligibility.py`: (country, t) with **no `label_any` positive in the preceding 12 months**, every one of those months present in the country's coverage (primary) |
| sensitivity variant | identical, calm window = 6 months — reported alongside, primary stays primary |
| target | `label_any` positive anywhere in [t+1, t+k], full window coverage required (existing `build_targets`) |
| horizons k | 1, 3, 6 months |
| eval window | 2015-01 → 2022-12 (2023-24 test window stays untouched) |
| contenders | B0 random (seed 20260703) · B1 persistence · B2 expanding base rate · B6 composite |
| support | strict common support: onset-eligible rows where the composite has a value; every contender scored on the identical rows |

### Primary metric — pooled within-country concordance

Over all (positive month, negative month) pairs drawn from **the same country**,
the fraction where the contender ranks the positive higher. Ties count 0.5.
Countries contribute in proportion to their pair count; a country with no
positives or no negatives contributes nothing.

This is the stratified c-statistic. It is the primary because it uses every
country with both classes present and does not require any country to have
enough months to support an AUROC of its own.

### Secondary metric — mean per-country AUROC

Per-country AUROC, then an unweighted mean across countries with **at least 3
positive and 3 negative** eligible months. Equal weight per country. Declared
secondary because the minimum-support rule discards countries the primary keeps,
and small-country AUROCs are unstable.

### Uncertainty

95% percentile confidence interval from **1000 bootstrap resamples over
countries** (resampling countries with replacement, not rows — the country is
the unit of independence here). Seed 20260703, matching the existing
`RANDOM_SEED`.

## Decision rule (declared before the run)

On the **primary metric, primary calm window**:

- **Signal**: the composite exceeds **0.55** at any horizon *and* its bootstrap
  95% CI excludes 0.5 at that horizon *and* it exceeds B2 at the same horizon.
  Then #573's negatives need revisiting, and the next step is the 2023-24 test
  window.
- **Negative**: anything else. #573's negatives are settled for the composite as
  constructed, and the composite should not be presented as predictive in any
  form.

No horizon is privileged, and no threshold moves after the run. If the composite
lands between 0.50 and 0.55, that is a negative, not a "promising trend".

## Degeneracies expected up front

- **The 133 never-labelled countries contribute nothing.** No positive months
  means no pairs. This is correct rather than a defect: they were never
  informative, and pooling let them inflate every metric computed so far.
- **B2 base rate should collapse toward 0.5.** Within a country, an expanding
  base rate is nearly monotone in time, so it should carry little within-country
  discrimination. If B2 stays high, the metric is not doing what this document
  claims and the result must not be read as a composite verdict.
- **B1 persistence retains some within-country variation**, for the reason
  amended into `docs/onset-eval.md` (A1): the calm window constrains months
  t−1…t−calm, not month t itself.
- **n will be far smaller than the onset exam's.** Only countries with both
  classes present contribute, and AUPR is not reported: it is not defined for a
  paired concordance.

## Interpretation limits (declared)

A null result here does **not** separate these two explanations:

1. The composite's construction does not carry signal.
2. The inputs do not carry signal, so no construction over them could.

#580 established that severity is near-degenerate across nearly every source and
#579 that the FIRMS value is the wrong quantity. Explanation 2 is live and this
exam cannot rule it out. A null should therefore be reported as "the composite
as constructed, over inputs as they currently exist, shows no within-country
discrimination" — not as "sensor data does not predict conflict".

A positive result is narrower than it looks too: it would show ranking skill
within country on a historical panel, not calibrated probability, and not
out-of-sample skill. The 2023-24 window and the forward journal remain the only
out-of-sample evidence.

## Published result — the single run (2026-07-22)

*Nothing above this line was edited after the run. Machine-generated copy:
`data/exports/within-country-eval.md` and `.json`.*

### Primary — calm window 12 months

| contender | k | n | countries | concordance | 95% CI | mean country AUROC | qualifying |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 random | 1 | 5764 | 56 | 0.449 | [0.332, 0.562] | 0.593 | 7 |
| B1 persistence | 1 | 5764 | 56 | 0.502 | [0.477, 0.535] | 0.563 | 7 |
| B2 base rate | 1 | 5764 | 56 | 0.304 | [0.181, 0.437] | 0.402 | 7 |
| **B6 composite** | 1 | 5764 | 56 | **0.489** | [0.374, 0.622] | 0.505 | 7 |
| B0 random | 3 | 5764 | 54 | 0.470 | [0.395, 0.537] | 0.484 | 50 |
| B1 persistence | 3 | 5764 | 54 | 0.501 | [0.480, 0.530] | 0.492 | 50 |
| B2 base rate | 3 | 5764 | 54 | 0.302 | [0.170, 0.441] | 0.305 | 50 |
| **B6 composite** | 3 | 5764 | 54 | **0.516** | [0.429, 0.589] | 0.504 | 50 |
| B0 random | 6 | 5761 | 52 | 0.460 | [0.401, 0.520] | 0.469 | 46 |
| B1 persistence | 6 | 5761 | 52 | 0.506 | [0.485, 0.525] | 0.498 | 46 |
| B2 base rate | 6 | 5761 | 52 | 0.286 | [0.153, 0.437] | 0.314 | 46 |
| **B6 composite** | 6 | 5761 | 52 | **0.531** | [0.474, 0.582] | 0.498 | 46 |

### Sensitivity — calm window 6 months

| contender | k | n | countries | concordance | 95% CI | mean country AUROC | qualifying |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 random | 1 | 7048 | 71 | 0.472 | [0.382, 0.556] | 0.495 | 27 |
| B1 persistence | 1 | 7048 | 71 | 0.514 | [0.484, 0.551] | 0.535 | 27 |
| B2 base rate | 1 | 7048 | 71 | 0.324 | [0.237, 0.412] | 0.386 | 27 |
| **B6 composite** | 1 | 7048 | 71 | **0.498** | [0.413, 0.600] | 0.524 | 27 |
| B0 random | 3 | 7048 | 67 | 0.479 | [0.424, 0.535] | 0.478 | 58 |
| B1 persistence | 3 | 7048 | 67 | 0.513 | [0.491, 0.541] | 0.517 | 58 |
| B2 base rate | 3 | 7048 | 67 | 0.321 | [0.230, 0.420] | 0.322 | 58 |
| **B6 composite** | 3 | 7048 | 67 | **0.520** | [0.439, 0.596] | 0.507 | 58 |
| B0 random | 6 | 7045 | 64 | 0.466 | [0.421, 0.511] | 0.472 | 56 |
| B1 persistence | 6 | 7045 | 64 | 0.511 | [0.493, 0.529] | 0.507 | 56 |
| B2 base rate | 6 | 7045 | 64 | 0.306 | [0.211, 0.417] | 0.317 | 56 |
| **B6 composite** | 6 | 7045 | 64 | **0.527** | [0.470, 0.581] | 0.512 | 56 |

### Verdict

**NEGATIVE.** No horizon met the pre-registered rule. The composite's best
primary result is 0.531 at k=6, below the declared 0.55 threshold, with a 95% CI
of [0.474, 0.582] that contains 0.5. Applied mechanically by `_verdict()`, not
by reading the table.

This is the fifth pre-registered negative. **#573's negatives are settled for
the composite as constructed.** The pooled exams were the wrong instrument, the
right instrument was built, and the composite failed it on its own terms —
absolutely, against the threshold and its own confidence interval, not merely
relative to a rival.

### The metric behaved as declared

B2 base rate was pre-registered to "collapse toward 0.5 by construction", as the
check that the stratification actually removes the cross-country register. It
collapsed hard: **0.93 pooled → 0.30 within country.** The register is gone,
which is what this exam was built to do.

### One result the protocol did not anticipate

B2 did not merely collapse to 0.5, it **inverted** — 0.286 to 0.324 across every
cell, consistently below chance. Within a country, an expanding base rate ranks
onset months *below* calm months. The protocol predicted collapse, not
inversion, and no mechanism is asserted here.

It does not change the verdict: the composite fails against a fixed threshold
and its own CI, independently of any rival. But a baseline reliably below chance
is either a real inverse relationship worth understanding or a defect in
`score_base_rate` under this support, and it should be investigated on its own
rather than left as a footnote.

### Observations that are not findings

- The composite rises monotonically with horizon in both calm windows (0.489 →
  0.516 → 0.531, and 0.498 → 0.520 → 0.527) and sits above B0 and B2 at k=3 and
  k=6. Under the pre-registered rule this is a **negative**, not a trend: every
  CI contains 0.5, and the protocol explicitly declared that 0.50-0.55 is a
  negative rather than a "promising trend". It is recorded because suppressing
  it would be selective reporting, not because it supports anything.
- At k=1 only **7 countries** met the 3-positive/3-negative minimum, so the
  mean-per-country column at that horizon rests on almost nothing. B0 random
  scoring 0.593 there is the clearest evidence of how unstable that cell is.
- n is 5,764 rows against 56 countries, far below the pooled exams — expected
  and declared, since only countries carrying both classes contribute.

### What this does not establish

Per the protocol's interpretation limits, this does not separate "the
composite's construction carries no signal" from "the inputs carry no signal".
#580 found severity to be a two or three level categorical across nearly every
source, and #579 that the FIRMS value is detection confidence rather than
intensity — non-monotonic against fire radiative power. Explanation 2 remains
live and untested.

The honest statement is: **the composite as constructed, over inputs as they
currently exist, shows no within-country discrimination.** It is not evidence
that sensor data cannot predict conflict.
