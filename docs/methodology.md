# Methodology — Composite Design, Pre-Registered Evaluation, Literature Baseline

*Single source of truth for the academic spine of the thesis. Three parts: (A) the pre-registered evaluation protocol (locked with Marco before any composite output is examined); (B) the literature backbone the thesis cites; (C) per-step methodology choices traced to that literature.*

Companion to the top-level [`README.md`](../README.md) (project plan), [`requirements.md`](requirements.md) (PX5928 university spec), and the [`architecture/`](architecture/) directory (how the system is built).

---

# Part A — Evaluation Protocol (Pre-Registered)

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

## Step 2 — Ground truth (hybrid, multi-modal)

**Sources**: [ACLED][acled] conflict event data + market-crisis label set + hazard-induced disruption label set. Multi-modal composite requires multi-modal ground truth to test fairly — labelling against ACLED alone would bias the evaluation toward the geopolitical input domain.

**Why this combination, not GDELT-as-truth**: GDELT cannot be both the input and the label — circular. ACLED is human-validated, peer-reviewed ([ACLED-vs-ICEWS-vs-GDELT comparison paper][icews-comparison]). Market-crisis dates come from authoritative external sources (NBER Business Cycle Dating Committee, IMF currency-crisis dataset, FRED VIX series). Hazard-induced disruption labels are pulled from [EM-DAT](https://www.emdat.be/) disaster declarations cross-referenced with [GDACS](https://www.gdacs.org/) red alerts.

**Event types treated as "positive" labels** (country-month level):

| Code | Domain | Event type | Threshold / source |
|---|---|---|---|
| `P1` | Geopolitical | Armed conflict onset | ≥1 ACLED "Battle" event with ≥10 reported fatalities |
| `P2` | Geopolitical | Mass protest escalation | ≥5 ACLED "Protests" events with violent escalation in 7-day window |
| `P3` | Geopolitical | State-based violence intensification | Month-over-month doubling of ACLED state-based fatalities |
| `P4` | Market | Country-level market crisis | One of: NBER recession onset (US only); IMF currency-crisis dataset entry; sovereign 10y-yield month-over-month spike > 200bps; equity index drawdown > 20% from rolling 12-month peak; VIX > 30 sustained 5 trading days (global, mapped to country exposure) |
| `P5` | Hazard | Hazard-induced societal disruption | EM-DAT disaster declaration with ≥100 deaths OR ≥100,000 affected, OR GDACS red-alert level, with composite stress sustained in following 30 days (the "induced disruption" filter, not raw hazard occurrence) |

**Multi-label handling**: a single country-month can carry multiple positive labels (e.g. P1 + P4 in a war + market-crash month). The primary classification target is **any-positive** (`P1 ∪ P2 ∪ P3 ∪ P4 ∪ P5`); per-domain breakdowns are reported in Step 9 sensitivity.

**Access**: ACLED is free for academic use with registered account. Pull historical data via [ACLED API][acled-api]. NBER + IMF + FRED + EM-DAT are all freely accessible with academic-use registration. Mirror locally under `/mnt/data/parquet/labels/` for reproducibility.

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

**Primary task**: At time `t`, given composite stress index value `S(c, t)` for country `c`, predict whether any of `{P1, P2, P3, P4, P5}` occurs in country `c` during `[t+1, t+k]`, where `k` = horizon length.

**Per-domain subtasks** (reported as secondary results, not the headline claim):
- Geopolitical-only target: any of `{P1, P2, P3}` in `[t+1, t+k]`
- Market-only target: `P4` in `[t+1, t+k]`
- Hazard-only target: `P5` in `[t+1, t+k]`

**Horizons evaluated**: `k ∈ {1, 3, 6}` months.

**Output**: per (country, month, horizon, target), the composite produces a continuous risk score, thresholded for classification. We report ROC and PR curves across all thresholds (not just one).

---

## Step 5 — Baselines

The composite must **beat** these to be worth keeping. List finalised before evaluation:

| ID | Baseline | What it is |
|---|---|---|
| `B0` | **Random** | Sanity check. AUROC ≈ 0.5. |
| `B1` | **Persistence** | "Same as last month." Strong baseline in autocorrelated systems. |
| `B2` | **Base rate** | Predict country's historical positive rate. |
| `B3` | **Geopolitical only** | Module B score (GDELT Goldstein), no composite. |
| `B4` | **Market only** | Module A score (yfinance + FRED + optional FinBERT), no composite. |
| `B5` | **Hazard only** | Module C score (USGS + GDACS + FIRMS), no composite. |
| `B6` | **Composite — equal weights** | Module D, equal-weighted A + B + C. |
| `B7` | **Composite — PCA weights** | Module D, weights from first PCA loading across A, B, C. |
| `B8` | **Composite — geometric mean** | Module D, geometric aggregation (less-compensatory robustness alternative). |

**Required result for thesis credibility**: `B6` or `B7` (or `B8`) strictly dominate **each** of `B3`, `B4`, `B5` on AUROC AND AUPR for the primary multi-label target. If they don't, the multi-modal claim fails — that is itself a defensible thesis result (negative findings count), and the Discussion must report it honestly. Per-domain subtasks (Step 4) are reported separately and are not required to beat the single-domain baseline of that same domain.

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
- Per-event-type breakdown (P1 / P2 / P3 / P4 / P5)
- Comparison to single-domain baseline lead times (B3 geopolitical / B4 market / B5 hazard)

**Caveat to document**: a composite that fires 6 months early on every country every month achieves great "lead time" and useless precision. Lead time **must** be reported alongside precision/recall, never alone.

---

## Step 8 — Case studies (pre-specified)

**Pre-register the case-study list before looking at composite output.** No cherry-picking.

**Selection rule**: from the test set (2023-2024), select 4 case studies stratified by domain + outcome:

- 1 × **clean true positive (geopolitical)** — composite breached well in advance, ACLED-confirmed P1/P2/P3 event followed
- 1 × **clean true positive (cross-domain)** — composite breached due to multi-domain signal, P4 or P5 followed (this is the multi-modal claim in case-study form)
- 1 × **false positive** — composite breached, no labelled event followed in horizon; analyse why
- 1 × **missed event** — labelled event occurred (any domain), composite did not breach; analyse why

**Selection method**: pick the densest event by primary-domain magnitude (ACLED fatalities for P1-3; max drawdown for P4; affected population for P5) in the test window, prior to running the composite. List candidate events here once Marco confirms.

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
5. **Source ablation** (multi-modal): drop one domain at a time — A only (geo + hazard), B only (market + hazard), C only (geo + market). Compare two-domain composites against the full three-domain composite. Already partially covered by B3 / B4 / B5 single-domain baselines.
6. **Country dropout**: leave-one-country-out cross-validation. Does any one country drive the result?

Each gets a table or figure. Pages don't need to be many — one figure per sensitivity test is enough.

---

## Step 10 — Reporting checklist

Before submission, the Results section must contain:

- [ ] Per-baseline AUROC, AUPR, Brier for all 9 baselines × 3 horizons × 4 targets (primary + 3 per-domain)
- [ ] ROC curves for B3, B4, B5, B6, B7 on the primary target (one figure)
- [ ] PR curves for B3, B4, B5, B6, B7 on the primary target (one figure)
- [ ] Per-domain breakdown table (does the composite beat each single-domain baseline on its own domain's target?)
- [ ] Calibration plot for composite
- [ ] Lead time histogram + median/IQR table, split by event-type domain
- [ ] 4 case studies (geo TP / cross-domain TP / FP / missed), 1 paragraph each
- [ ] Weight sensitivity Monte Carlo figure (Dirichlet over A, B, C weights)
- [ ] Source-ablation table (two-domain composites vs full three-domain)
- [ ] Country-LOOCV table or boxplot
- [ ] Explicit list of **limitations** (FinBERT validity as auxiliary signal, GDELT noise, hazard-induced-disruption filter sensitivity, market-coverage gaps for emerging markets, ACLED coverage gaps in some regions, short test window)
- [ ] Statement on industrial applications (Marco's brief requirement)

---

## Open questions for Marco (raise at first meeting)

1. Is ACLED + NBER + IMF + EM-DAT the right combined ground-truth set for a multi-modal composite, or would he prefer a single-domain ground truth with multi-domain inputs?
2. Is the 2015-2021 / 2022 / 2023-2024 split acceptable? Any specific historical event period he wants forced into the test window?
3. Country panel: agree the list of 20-30 in advance, or stratify automatically by FSI? Need balanced country exposure across geopolitical / market / hazard event density.
4. Does the multi-modal-claim framing (B6/B7 strictly dominate each of B3, B4, B5) need a falsifiable margin (e.g. "Δ AUPR > 0.05") to count as success?
5. Acceptable for case studies to be selected by per-domain magnitude, or does he have specific events in mind?
6. Hazard inclusion: is `P5` (hazard-induced disruption with sustained composite stress) the right operationalisation, or would he prefer raw hazard occurrence as a positive label?

---

## Document version (Part A)

- **v1.0** — initial draft. **Lock with Marco before Week 4 (start of evaluation harness coding).**

---

# Part B — Literature Baseline

The literature backbone that turns the project from "cool dashboard" into "defensible MSc thesis." If a reviewer asks "what literature is your work built on?", this part is the answer.

**Use this as**: (1) reading list, ordered by priority; (2) citation reservoir for Introduction + Discussion; (3) quick-reference for methodology choices.

## B.1 — Conflict Early Warning Systems (the field)

The peer-reviewed field your thesis sits in. Cite all four. The first is non-negotiable.

| # | Reference | Why |
|---|---|---|
| 1.1 | **Hegre et al. (2019)** — [ViEWS: A political violence early-warning system][views-paper] (*Journal of Peace Research*) | Single most important paper. 95% accuracy, 35% FP. Defines transparent CEWS methodology. Your evaluation metrics (AUROC, AUPR, Brier) come from this tradition. |
| 1.2 | **Davies et al. (2023)** — [A review and comparison of conflict early warning systems][cews-review] (*Int. J. of Forecasting*) | Survey paper. AUROC + AUPR + Brier as standard. Cite when motivating metric choice. |
| 1.3 | **Goldstone et al. (2010)** — [A Global Model for Forecasting Political Instability][goldstone-pitf] (*American J. of Political Science*) | Foundational PITF paper. Cite when introducing instability prediction as a field. |
| 1.4 | **ViEWS Forecasting site** — [viewsforecasting.org][views-site] | Live system. Useful for showing the reviewer the state-of-the-art baseline you're aware of. |

**Use in thesis**: Introduction → "Modern CEWS methodology is established by Hegre et al. (2019) and surveyed by Davies et al. (2023)..." Discussion → "Unlike ViEWS, which uses [X], our approach..."

## B.2 — Composite Indicators (the methodology authority)

Every composite-scoring choice in the thesis must trace back to this handbook.

| # | Reference | Why |
|---|---|---|
| 2.1 | **OECD/JRC (2008)** — [Handbook on Constructing Composite Indicators][jrc-handbook] | The standard reference. 162 pages. Chapters 4 (normalisation), 6 (weighting), 7 (robustness) are the priority. Cite every methodology decision against this. |
| 2.2 | **JRC** — [Composite Indicators Research Centre][jrc-coin] | Worked examples and software (PCA, sensitivity analysis). |

**Use**: Methods section opens with "We construct the composite stress index following the OECD/JRC ten-step methodology (Nardo et al., 2008). The choice of z-score normalisation is justified by [Section 4.x]..."

JRC 10 steps (memorise): theoretical framework → data selection → imputation → multivariate analysis → normalisation → weighting → aggregation → uncertainty/sensitivity → back to data → presentation. Your Methods section walks through these literally.

## B.3 — Event Data Sources (and their limits)

Validity papers. Cite these so the reviewer cannot accuse you of ignoring known limitations of GDELT.

| # | Reference | Why |
|---|---|---|
| 3.1 | **Wang et al. (MDPI, 2025)** — [Research on Development and Application of the GDELT Event Database][gdelt-mdpi] | Audits GDELT accuracy at ~55% on key fields, ~20% redundancy. Cite when defending your deduplication step. |
| 3.2 | **Wallace (2014)** — [Raining on the Parade: Cautions Regarding GDELT][gdelt-pvg] (*Political Violence at a Glance*) | Classic GDELT critique. Tone construct validity, machine-coding limits. Cite when explaining why you use Goldstein not raw tone. |
| 3.3 | **Öberg & Yilmaz (2025)** — [Measurement issues in conflict event data][oberg-yilmaz] (*Research & Politics*) | Recent measurement-quality paper. Useful in Discussion for limitations framing. |
| 3.4 | **ACLED (2019)** — [Comparing Conflict Data (Working Paper)][icews-comparison] | Side-by-side ACLED / ICEWS / GDELT comparison. Cite when justifying ACLED as ground truth. |
| 3.5 | **Schrodt** — [CAMEO Codebook][cameo-codebook] | Standard taxonomy for event coding. Cite when filtering GDELT themes. |
| 3.6 | **Leetaru & Schrodt (2013)** — [GDELT: Global Data on Events, Location, Tone, 1979-2012][gdelt-original] | Original GDELT paper. Cite once when introducing the source. |

Data source URLs: [GDELT GKG 2.0][gdelt-data], [ACLED][acled] + [ACLED CAST][acled-cast], [USGS Earthquake Feeds][usgs-quakes], [NASA FIRMS][nasa-firms], [Open-Meteo][open-meteo].

## B.4 — Market signals and financial sentiment (Module A)

Module A's intellectual foundation, including the honest acknowledgement of limits.

| # | Reference | Why |
|---|---|---|
| 4.1 | **Araci (2019)** — [FinBERT: Financial Sentiment Analysis with Pre-trained Language Models][finbert-original] (arXiv) | Original FinBERT paper. Cite once when introducing the model. |
| 4.2 | **Yang et al. (2024)** — [Innovative Sentiment Analysis and Prediction of Stock Price Using FinBERT, GPT-4 and Logistic Regression][finbert-arxiv] | Reports R²≈0.01 for downstream price prediction. Cite when noting that news sentiment ≠ market prediction. **Needed for FinBERT-honesty framing.** |
| 4.3 | **MDPI (2025)** — [Fine-Tuning and Explaining FinBERT for Sector-Specific Financial News][finbert-finetune] | Sector-aware fine-tuning, macro F1 = 0.707 with fine-tuning vs 0.555 zero-shot. Useful if you fine-tune. |
| 4.4 | **Zebrowski & Afli (2024)** — [Predicting Country Instability Using Bayesian Deep Learning and Random Forest][instability-arxiv] | GDELT + GTD ground truth. Methodologically closer to your work than WorldMonitor. Cite as a comparison point. |

**Phrasing for thesis** (use verbatim): "We use FinBERT (Araci, 2019) as an auxiliary news-tone signal within Module A. We note that FinBERT-derived sentiment has limited direct predictive power for market prices (R² ≈ 0.01 in Yang et al., 2024); accordingly, we use it as one input to the market component of a multi-modal composite stress index rather than a standalone market predictor."

## B.5 — Instability indices in use (composite comparators)

Cite at least two; engage with their methodology in Discussion.

| # | Reference | Why |
|---|---|---|
| 5.1 | **Fund for Peace** — [Fragile States Index Methodology][fsi-methodology] | 12 indicators across 4 categories, CAST framework, annual ranking of 178 countries. The main published composite-instability index. Cite + briefly compare in Methods. |
| 5.2 | **ACLED CAST** — [Conflict Alert System][acled-cast] | Rolling 4-week forecast per country. Validated. Useful baseline / future-work direction. |

(Note: WorldMonitor's "CII" composite is proprietary with no published methodology — do not cite as a methodology comparator.)

## B.6 — Reference architectures (NOT methodology citations)

These are hobbyist projects without published methodology. List here so you remember not to cite them academically.

| # | Reference | Status |
|---|---|---|
| 6.1 | [WorldMonitor (koala73)][worldmonitor-repo] | Hobby project, AGPL. "CII v8" proprietary, undocumented. Architectural inspiration only. |
| 6.2 | [Shadowbroker (BigBodyCobain)][shadowbroker-repo] | Self-described "experimental testnet." Stack you can borrow (FastAPI + MapLibre + APScheduler). Not a methodology source. |

**Allowed use**: a single footnote in the Introduction noting that public-facing OSINT dashboards exist (Shadowbroker, WorldMonitor) but lack published methodology — motivating the need for a methodologically grounded approach.

## B.7 — Citation snippets

```text
Hegre, H., Allansson, M., Basedau, M., et al. (2019). ViEWS: A political
violence early-warning system. Journal of Peace Research, 56(2), 155-174.
https://doi.org/10.1177/0022343319823860

Nardo, M., Saisana, M., Saltelli, A., et al. (2008). Handbook on Constructing
Composite Indicators: Methodology and User Guide. OECD Publishing.
https://doi.org/10.1787/9789264043466-en

Goldstone, J. A., Bates, R. H., Epstein, D. L., et al. (2010). A Global Model
for Forecasting Political Instability. American Journal of Political Science,
54(1), 190-208.

Leetaru, K., & Schrodt, P. A. (2013). GDELT: Global Data on Events, Location,
and Tone, 1979-2012. International Studies Association Annual Convention.

Araci, D. (2019). FinBERT: Financial Sentiment Analysis with Pre-trained
Language Models. arXiv:1908.10063.

Öberg, M., & Yilmaz, M. C. (2025). Measurement issues in conflict event data.
Research & Politics. https://doi.org/10.1177/20531680251362440

Wallace, J. (2014). Raining on the Parade: Some Cautions Regarding GDELT.
Political Violence at a Glance.

Davies, S., et al. (2023). A review and comparison of conflict early warning
systems. International Journal of Forecasting.

Zebrowski, A., & Afli, H. (2024). Predicting Country Instability Using
Bayesian Deep Learning and Random Forest. arXiv:2411.06639.

Yang, K., et al. (2024). Innovative Sentiment Analysis and Prediction of
Stock Price Using FinBERT, GPT-4 and Logistic Regression. arXiv:2412.06837.

Fund for Peace. (2024). Fragile States Index Methodology.
https://fragilestatesindex.org/methodology/

ACLED. (2019). Comparing Conflict Data (Working Paper).
https://acleddata.com/sites/default/files/wp-content-archive/uploads/2022/02/ACLED_WorkingPaper_ComparisonAnalysis_2019.pdf
```

## B.8 — Reading priority (if you read nothing else)

1. **Hegre et al. 2019 (ViEWS)** — *2 hours, must read*
2. **JRC Handbook chapters 4, 6, 7** — *2-3 hours, must skim*
3. **Wallace 2014 (GDELT critique)** — *15 min, must read*
4. **Davies et al. 2023 (CEWS review)** — *1 hour, must skim*
5. **FSI Methodology** — *30 min, must skim*

Total: ~6 hours. Pays back tenfold in writing speed and defensibility.

---

[views-paper]: https://journals.sagepub.com/doi/full/10.1177/0022343319823860
[views-site]: https://viewsforecasting.org/
[cews-review]: https://www.sciencedirect.com/science/article/pii/S0169207023000018
[goldstone-pitf]: https://www.tandfonline.com/doi/abs/10.1111/j.1540-5907.2009.00426.x
[jrc-handbook]: https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf
[jrc-coin]: https://composite-indicators.jrc.ec.europa.eu/
[acled]: https://acleddata.com/
[acled-api]: https://apidocs.acleddata.com/
[acled-cast]: https://acleddata.com/conflict-alert-system/
[icews-comparison]: https://acleddata.com/sites/default/files/wp-content-archive/uploads/2022/02/ACLED_WorkingPaper_ComparisonAnalysis_2019.pdf
[fsi-rankings]: https://fragilestatesindex.org/
[fsi-methodology]: https://fragilestatesindex.org/methodology/
[oberg-yilmaz]: https://journals.sagepub.com/doi/10.1177/20531680251362440
[gdelt-data]: https://www.gdeltproject.org/data.html
[gdelt-mdpi]: https://www.mdpi.com/2306-5729/10/10/158
[gdelt-pvg]: https://politicalviolenceataglance.org/2014/02/20/raining-on-the-parade-some-cautions-regarding-the-global-database-of-events-language-and-tone-dataset/
[gdelt-original]: http://data.gdeltproject.org/documentation/ISA.2013.GDELT.pdf
[cameo-codebook]: http://eventdata.parusanalytics.com/data.dir/cameo.html
[usgs-quakes]: https://earthquake.usgs.gov/earthquakes/feed/
[nasa-firms]: https://firms.modaps.eosdis.nasa.gov/
[open-meteo]: https://open-meteo.com/
[finbert-original]: https://arxiv.org/abs/1908.10063
[finbert-arxiv]: https://arxiv.org/pdf/2412.06837
[finbert-finetune]: https://www.mdpi.com/2079-9292/14/23/4680
[instability-arxiv]: https://arxiv.org/abs/2411.06639
[worldmonitor-repo]: https://github.com/koala73/worldmonitor
[shadowbroker-repo]: https://github.com/BigBodyCobain/Shadowbroker
