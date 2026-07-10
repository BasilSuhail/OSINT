# The Onset Evaluation — pre-registered (#380)

*Declared 2026-07-10, before the evaluation was run. Everything below was
fixed first; the run happened once, after; the results section quotes that
single run. Changes are versioned amendments, never edits.*

## Why this exam exists

The pre-registered three-domain test (#282, 2026-07-09) graded the composite
at AUROC ~0.502 against a per-country base rate of ~0.929 on the *incidence*
target — "will there be conflict events next month". Chronically conflicted
countries answer yes every month, so a no-skill register of known
troublemakers aces that exam. The composite z-scores each country against its
own past, deliberately erasing exactly that register: what remains is a
*deviation* — an onset/escalation instrument. This is the standard
incidence-vs-onset distinction in the conflict-forecasting literature, and
this document gives the deviation instrument the exam it was built for,
fixed before anyone looked at the answer.

## The protocol (fixed)

| element | value |
|---|---|
| onset eligibility | (country, t) with **no `label_any` positive in the preceding 12 months** (primary); every one of those 12 months must exist in the country's panel coverage — unknown calm is not calm |
| sensitivity variant | identical, calm window = 6 months — declared here, reported alongside, primary stays primary |
| target | `label_any` positive anywhere in [t+1, t+k], full window coverage required (existing `build_targets`) |
| horizons k | 1, 3, 6 months |
| eval window | 2015-01 → 2022-12 (issuance months; 2023-24 test window stays untouched) |
| contenders | B0 random (seed 20240501) · B1 persistence · B2 expanding base rate · B6 composite v1.0 |
| support | strict common support: only onset-eligible rows where the composite has a value; every contender scored on the identical rows |
| metrics | AUROC, AUPR (existing `app.baselines.metrics`); no Brier for non-probability scores |
| secondary (exploratory, declared) | the WS-F indicator variants (`signal_*`, raw + abs) on the same onset support — context, not headline |

## Degeneracies expected up front

- ~~**B1 persistence is constant 0 on onset months by construction**~~ —
  **this expectation was wrong** (see amendment A1): the calm window
  constrains months t−1…t−calm, not month t itself, so persistence still
  varies with month t's own label. The protocol is unchanged; only the
  stated expectation was corrected, after the run, without touching any
  number.
- **B2 loses most of its edge by construction**: within onset-eligible rows,
  the chronic-conflict register that carried it on incidence is heavily
  suppressed. Whatever advantage survives (long-history countries with old
  positives before the calm window) is honest and stays in the number.
- The positive rate on onset months will be far below the incidence 26–39 % —
  AUPR must be read against the reported base rate, not against the incidence
  exam's.

## Published result — the single run (2026-07-10)

*The protocol above was frozen first; `make onset-eval` then ran once. The
JSON export is the artefact of record; the report is deterministic and
regenerable.*

Primary (12-month calm), strict common support n = 5,764 onset months,
positive rate 1.7 % / 4.7 % / 8.6 % at k = 1/3/6:

| k | B6 composite | B2 base rate | B1 persistence | B0 random |
|---|---|---|---|---|
| 1 | **0.496** | 0.744 | 0.544 | 0.467 |
| 3 | **0.520** | 0.748 | 0.535 | 0.497 |
| 6 | **0.526** | 0.749 | 0.533 | 0.488 |

Sensitivity (6-month calm, n = 7,048): composite 0.521 / 0.515 / 0.517 —
same picture.

**The composite is a coin flip on its own exam too, and that is the
published result.** The incidence excuse is spent: B2's surviving edge
(0.744) comes from pre-calm-window history — even among countries calm for a
full year, long-run relapse risk dominates, and the composite's deviation
signal adds nothing measurable on top. Secondary (exploratory): the
best onset indicator is |geopolitical z| at 0.558 — weak, but above the
composite and a *different* leader than the incidence exam's |hazard z|
(0.593), consistent with the domains carrying different exam-specific
information that the current one-sided combination discards.

## Amendment log

- **A1 (2026-07-10, post-run):** the expected-degeneracies section wrongly
  claimed B1 persistence would be constant 0 on onset months; the calm
  window never constrained month t itself. Expectation corrected, protocol
  and numbers untouched.
