# Evaluation Protocol — Pre-Registered Methodology

*Companion to [`master-plan.md`](master-plan.md) and [`literature-baseline.md`](literature-baseline.md). This document defines **how the composite stress index will be evaluated, decided before the data is examined**, to avoid p-hacking and post-hoc cherry-picking.*

**Critical rule**: this protocol is finalised with Marco at the first supervisory meeting. Once locked, it does not change based on what the data shows. Changes after data inspection must be documented as exploratory, not confirmatory.

---

## Quick navigation

- [Step 1 — Why pre-register](#step-1--why-pre-register)
- [Step 2 — Ground truth](#step-2--ground-truth)
- [Step 3 — Time period & data split](#step-3--time-period--data-split)
- [Step 4 — Prediction task definition](#step-4--prediction-task-definition)
- [Step 5 — Baselines](#step-5--baselines)
- [Step 6 — Metrics](#step-6--metrics)
- [Step 7 — Detection delay analysis](#step-7--detection-delay-analysis)
- [Step 8 — Case studies (pre-specified)](#step-8--case-studies-pre-specified)
- [Step 9 — Sensitivity & robustness](#step-9--sensitivity--robustness)
- [Step 10 — Reporting checklist](#step-10--reporting-checklist)

---

## Step 1 — Why pre-register

"We found cases where the composite preceded events" is **post-hoc cherry-picking**. Examiners and reviewers spot this instantly. The fix:

- Decide the evaluation question *before* looking at composite output
- Pick metrics standard in the field ([ViEWS][views-paper] uses AUROC/AUPR/Brier — so do you)
- Commit to a baseline comparison so "composite beat single-signal" is testable, not asserted
- Document the protocol in this file, dated and version-controlled before any results are generated

This is the difference between "I built something" and "I evaluated something."

---

## Step 2 — Ground truth

**Source**: [ACLED][acled] event data.

**Why ACLED, not GDELT-as-truth**: GDELT cannot be both the input and the label — circular. ACLED is human-validated, peer-reviewed, and the [ACLED-vs-ICEWS-vs-GDELT comparison paper][icews-comparison] documents ACLED's lower noise.

**Event types treated as "positive" labels** (country-month level):

| Code | Event type | Threshold |
|---|---|---|
| `P1` | Armed conflict onset | ≥1 ACLED "Battle" event with ≥10 reported fatalities |
| `P2` | Mass protest escalation | ≥5 ACLED "Protests" events with violent escalation in 7-day window |
| `P3` | State-based violence intensification | month-over-month doubling of ACLED state-based fatalities |

**Access**: ACLED is free for academic use with registered account. Pull historical data via [ACLED API][acled-api]. Mirror locally to `/mnt/data/acled/` for reproducibility.

---

## Step 3 — Time period & data split

| Split | Years | Use |
|---|---|---|
| **Training** | 2015-2021 | Composite weights, threshold selection |
| **Validation** | 2022 | Hyperparameter tuning (e.g. rolling-window length, normalisation choice) |
| **Test** | 2023-2024 | Held-out final evaluation. **Not touched until methodology locked.** |
| **Live demo** | 2025-2026 (Pi-collected) | Demonstration of running system. Not part of formal evaluation. |

**Country panel**: select 20-30 countries covering range of instability levels (use [FSI 2024 ranking][fsi-rankings] as the basis: top-10 fragile, bottom-10 stable, 10 mid-range). Pre-specify country list before data inspection.

**Unit of analysis**: country-month (matches ViEWS convention).

---

## Step 4 — Prediction task definition

**Task**: At time `t`, given composite stress index value `S(c, t)` for country `c`, predict whether any of `{P1, P2, P3}` occurs in country `c` during `[t+1, t+k]`, where `k` = horizon length.

**Horizons evaluated**: `k ∈ {1, 3, 6}` months.

**Output**: per (country, month, horizon), the composite produces a continuous risk score, thresholded for classification. We report ROC and PR curves across all thresholds (not just one).

---

## Step 5 — Baselines

The composite must **beat** these to be worth keeping. List finalised before evaluation:

| ID | Baseline | What it is |
|---|---|---|
| `B0` | **Random** | Sanity check. AUROC ≈ 0.5. |
| `B1` | **Persistence** | "Same as last month." Strong baseline in autocorrelated systems. |
| `B2` | **Base rate** | Predict country's historical positive rate. |
| `B3` | **GDELT only** | Module B score, no composite. |
| `B4` | **Finance only** | Module A score, no composite. |
| `B5` | **Composite (equal weights)** | Module D, equal-weighted A+B. |
| `B6` | **Composite (PCA weights)** | Module D, weights from first PCA loadings. |

**Required result for thesis credibility**: `B5` or `B6` strictly dominate `B3` and `B4` on AUROC AND AUPR. If they don't, the composite adds no information — that is itself a defensible thesis result (negative findings count), but you must report it honestly.

---

## Step 6 — Metrics

All three standard in conflict forecasting per [Davies et al. 2023 review][cews-review]:

| Metric | What it tells you | Why it matters |
|---|---|---|
| **AUROC** | Discrimination across thresholds | Standard, threshold-agnostic. |
| **AUPR** | Precision-recall under class imbalance | **Critical** — instability events are rare. AUROC inflates under imbalance, AUPR doesn't. |
| **Brier score** | Calibration of probabilities | Are your probability estimates honest? |
| **Lead time distribution** | See [Step 7](#step-7--detection-delay-analysis) | Specific to early-warning use case. |

Report **all four**, per baseline, per horizon. Tables go in Results section.

---

## Step 7 — Detection delay analysis

Per Marco's brief: "detection delay, false positives, missed events."

**Definition**: for each true positive event, lead time = months between first composite-threshold breach and ACLED-confirmed event.

**Report**:
- Median + IQR of lead time
- Histogram of lead times
- Per-event-type breakdown (P1 / P2 / P3)
- Comparison to baseline lead times (B3, B4)

**Caveat to document**: a composite that fires 6 months early on every country every month achieves great "lead time" and useless precision. Lead time **must** be reported alongside precision/recall, never alone.

---

## Step 8 — Case studies (pre-specified)

**Pre-register the case-study list before looking at composite output.** No cherry-picking.

**Selection rule**: from the test set (2023-2024), select 3 case studies stratified by outcome:

- 1 × **clean true positive** (composite breached well in advance, ACLED-confirmed event followed)
- 1 × **false positive** (composite breached, no event followed — explain why)
- 1 × **missed event** (ACLED event occurred, composite did not breach — explain why)

**Selection method**: pick the most ACLED-fatality-dense event of each type that occurs in the test set window, prior to running the composite. List the candidate events here once Marco confirms.

Pre-specified candidate countries (placeholder — finalise with Marco):
1. _____________________
2. _____________________
3. _____________________

This protects you against the "you only show the wins" critique.

---

## Step 9 — Sensitivity & robustness

Per [JRC handbook][jrc-handbook] Step 8 (uncertainty / sensitivity analysis):

1. **Weight perturbation**: Monte Carlo over weights drawn from Dirichlet, report AUROC distribution. Is performance weight-sensitive?
2. **Normalisation alternatives**: z-score (primary) vs min-max vs ranking. Does ranking change materially?
3. **Aggregation alternatives**: linear (primary) vs geometric mean. Does the geometric (less compensatory) hold up?
4. **Rolling-window length**: 30d / 60d / 90d. Which gives best validation-set AUPR?
5. **Source ablation**: drop GDELT — does finance alone do as well? Drop finance — does GDELT alone? (This is B3 / B4.)
6. **Country dropout**: leave-one-country-out cross-validation. Does any one country drive the result?

Each gets a table or figure. Pages don't need to be many — one figure per sensitivity test is enough.

---

## Step 10 — Reporting checklist

Before submission, the Results section must contain:

- [ ] Per-baseline AUROC, AUPR, Brier for all 7 baselines × 3 horizons
- [ ] ROC curves for B3, B4, B5, B6 (one figure)
- [ ] PR curves for B3, B4, B5, B6 (one figure)
- [ ] Calibration plot for composite
- [ ] Lead time histogram + median/IQR table
- [ ] 3 case studies (1 TP, 1 FP, 1 missed), 1 paragraph each
- [ ] Weight sensitivity Monte Carlo figure
- [ ] Source-ablation table (Step 9.5)
- [ ] Country-LOOCV table or boxplot
- [ ] Explicit list of **limitations** (FinBERT validity, GDELT noise, ACLED coverage gaps in some regions, short test window)
- [ ] Statement on industrial applications (Marco's brief requirement)

---

## Open questions for Marco (raise at first meeting)

1. Is ACLED the right ground-truth source, or would he prefer UCDP/GED? (UCDP has higher quality for state-based armed conflict but lower temporal resolution.)
2. Is the 2015-2021 / 2022 / 2023-2024 split acceptable? Any specific historical event period he wants forced into the test window?
3. Country panel: agree the list of 20-30 in advance, or stratify automatically by FSI?
4. Does the negative-result framing (composite ≥ single-signal baselines) need a falsifiable threshold (e.g. "Δ AUPR > 0.05") to count as success?
5. Acceptable for case studies to be selected by fatality density, or does he have specific events in mind?

---

## Document version

- **v1.0** — initial draft. **Lock with Marco before Week 4 (start of evaluation harness coding).**

---

[views-paper]: https://journals.sagepub.com/doi/full/10.1177/0022343319823860
[cews-review]: https://www.sciencedirect.com/science/article/pii/S0169207023000018
[jrc-handbook]: https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf
[acled]: https://acleddata.com/
[acled-api]: https://apidocs.acleddata.com/
[icews-comparison]: https://acleddata.com/sites/default/files/wp-content-archive/uploads/2022/02/ACLED_WorkingPaper_ComparisonAnalysis_2019.pdf
[fsi-rankings]: https://fragilestatesindex.org/
