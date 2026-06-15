# Literature Baseline — Required Reading & Citations

*Companion to [`master-plan.md`](master-plan.md) and [`evaluation-protocol.md`](evaluation-protocol.md). This is the literature backbone that turns the project from "cool dashboard" into "defensible MSc thesis." If a reviewer asks "what literature is your work built on?" — this document is the answer.*

**Use this as**: (1) reading list, ordered by priority; (2) citation reservoir for Introduction + Discussion; (3) quick-reference for methodology choices.

---

## Quick navigation

- [Step 1 — Conflict Early Warning Systems (the field you're in)](#step-1--conflict-early-warning-systems)
- [Step 2 — Composite Indicators (your methodology)](#step-2--composite-indicators)
- [Step 3 — Event Data Sources (and their limits)](#step-3--event-data-sources)
- [Step 4 — Financial News Sentiment (your Module A)](#step-4--financial-news-sentiment)
- [Step 5 — Instability Indices in use](#step-5--instability-indices-in-use)
- [Step 6 — Reference architectures (NOT methodology citations)](#step-6--reference-architectures)
- [Step 7 — Citation template snippets](#step-7--citation-template-snippets)

---

## Step 1 — Conflict Early Warning Systems

**The peer-reviewed field your thesis sits in.** Cite all four. The first is non-negotiable.

| # | Reference | Why |
|---|---|---|
| 1.1 | **Hegre et al. (2019)** — [ViEWS: A political violence early-warning system][views-paper] (*Journal of Peace Research*) | The single most important paper for your thesis. Reports 95% accuracy, 35% FP. Defines transparent CEWS methodology. Your evaluation metrics (AUROC, AUPR, Brier) come from this tradition. |
| 1.2 | **Davies et al. (2023)** — [A review and comparison of conflict early warning systems][cews-review] (*Int. J. of Forecasting*) | Survey paper. Six projects, AUROC + AUPR + Brier as standard. Cite when motivating metric choice. |
| 1.3 | **Goldstone et al. (2010)** — [A Global Model for Forecasting Political Instability][goldstone-pitf] (*American J. of Political Science*) | Foundational PITF paper. Cite when introducing instability prediction as a field. |
| 1.4 | **ViEWS Forecasting site** — [viewsforecasting.org][views-site] | Live system. Useful for showing reviewer the state-of-the-art baseline you're aware of (without claiming to match it). |

**How to use in thesis**: Introduction → "Modern CEWS methodology is established by Hegre et al. (2019) and surveyed by Davies et al. (2023). Both report AUROC/AUPR as the standard metric…" Discussion → "Unlike ViEWS, which uses [X], our approach…"

---

## Step 2 — Composite Indicators

**Your methodology authority.** Every composite-scoring choice in the thesis must trace back to this handbook.

| # | Reference | Why |
|---|---|---|
| 2.1 | **OECD/JRC (2008)** — [Handbook on Constructing Composite Indicators][jrc-handbook] | The standard reference. 162 pages. You don't need to read all of it — focus on chapters 4 (normalisation), 6 (weighting), 7 (robustness). Cite every methodology decision against this. |
| 2.2 | **JRC** — [Composite Indicators Research Centre tools page][jrc-coin] | Has worked examples and software (PCA, sensitivity analysis). Useful for implementation. |

**How to use**: Methods section opens with "We construct the composite stress index following the OECD/JRC ten-step methodology (Nardo et al., 2008). The choice of z-score normalisation is justified by [Section 4.x]…"

The standard 10 steps (memorise these):

1. Theoretical framework
2. Data selection
3. Imputation of missing data
4. Multivariate analysis
5. Normalisation
6. Weighting
7. Aggregation
8. Uncertainty / sensitivity analysis
9. Back to the data (interpret what you found)
10. Presentation & visualisation

Your Methods section *literally walks through these steps*. Examiner will see the structure and recognise it.

---

## Step 3 — Event Data Sources

**The validity papers.** Cite these so the reviewer cannot accuse you of ignoring known limitations of GDELT.

| # | Reference | Why |
|---|---|---|
| 3.1 | **Wang et al. (MDPI, 2025)** — [Research on Development and Application of the GDELT Event Database][gdelt-mdpi] | Audits GDELT accuracy at ~55% on key fields, ~20% redundancy. Cite when defending your deduplication step. |
| 3.2 | **Wallace (2014)** — [Raining on the Parade: Cautions Regarding GDELT][gdelt-pvg] (*Political Violence at a Glance*) | The classic GDELT critique. Tone construct validity, machine-coding limits. Cite when explaining why you use Goldstein not raw tone. |
| 3.3 | **Öberg & Yilmaz (2025)** — [Measurement issues in conflict event data][oberg-yilmaz] (*Research & Politics*) | Recent measurement-quality paper. Useful in Discussion for limitations framing. |
| 3.4 | **ACLED (2019)** — [Comparing Conflict Data (Working Paper)][icews-comparison] | Side-by-side ACLED / ICEWS / GDELT comparison. Cite when justifying ACLED as ground truth. |
| 3.5 | **Schrodt** — [CAMEO Codebook][cameo-codebook] | Standard taxonomy for event coding. Cite when filtering GDELT themes. |
| 3.6 | **Leetaru & Schrodt (2013)** — [GDELT: Global Data on Events, Location, Tone, 1979-2012][gdelt-original] | Original GDELT paper. Cite once when introducing the source. |

**Data source pages** (cite as URLs):
- [GDELT GKG 2.0][gdelt-data]
- [ACLED][acled] + [ACLED CAST][acled-cast]
- [USGS Earthquake Feeds][usgs-quakes]
- [NASA FIRMS][nasa-firms]
- [Open-Meteo][open-meteo]

---

## Step 4 — Financial News Sentiment

**Module A's intellectual foundation.** Also where you must honestly acknowledge limits.

| # | Reference | Why |
|---|---|---|
| 4.1 | **Araci (2019)** — [FinBERT: Financial Sentiment Analysis with Pre-trained Language Models][finbert-original] (arXiv) | Original FinBERT paper. Cite once when introducing the model. |
| 4.2 | **Yang et al. (2024)** — [Innovative Sentiment Analysis and Prediction of Stock Price Using FinBERT, GPT-4 and Logistic Regression][finbert-arxiv] | Reports the R²≈0.01 number. Cite when noting that news sentiment ≠ market prediction. **You need this honesty in the thesis.** |
| 4.3 | **MDPI (2025)** — [Fine-Tuning and Explaining FinBERT for Sector-Specific Financial News][finbert-finetune] | Sector-aware fine-tuning, macro F1 = 0.707 with fine-tuning vs 0.555 zero-shot. Useful if you fine-tune. |
| 4.4 | **Zebrowski & Afli (2024)** — [Predicting Country Instability Using Bayesian Deep Learning and Random Forest][instability-arxiv] | Uses GDELT + ground-truth validation via Global Terrorism Database. Methodologically closer to your work than WorldMonitor. Cite as a comparison point. |

**Phrasing for thesis** (use this verbatim): "We use FinBERT (Araci, 2019) for financial news sentiment classification. We note that FinBERT-derived sentiment has limited direct predictive power for market prices (R² ≈ 0.01 in Yang et al., 2024); accordingly, we use it as one input signal to a composite stress index rather than a standalone market predictor."

---

## Step 5 — Instability Indices in Use

**Comparators for your composite.** Cite at least two; ideally engage with their methodology in your Discussion.

| # | Reference | Why |
|---|---|---|
| 5.1 | **Fund for Peace** — [Fragile States Index Methodology][fsi-methodology] | 12 indicators across 4 categories, CAST framework, annual ranking of 178 countries. **The main published composite-instability index.** Cite + briefly compare in Methods. |
| 5.2 | **WorldMonitor's CII** — proprietary, **no published methodology**. **Do not cite as a methodology comparator** — use only as anecdotal interest, if at all. | (Avoid this trap.) |
| 5.3 | **ACLED CAST** — [Conflict Alert System][acled-cast] | Rolling 4-week forecast per country. Validated. Useful baseline / future-work direction. |

---

## Step 6 — Reference Architectures

**These are NOT in your thesis literature review.** They're hobbyist projects without published methodology. List here so you remember not to cite them academically.

| # | Reference | Status |
|---|---|---|
| 6.1 | [WorldMonitor (koala73)][worldmonitor-repo] | 56k★ hobby project, AGPL. "CII v8" proprietary, undocumented. Architectural inspiration only. |
| 6.2 | [Shadowbroker (BigBodyCobain)][shadowbroker-repo] | Self-described "experimental testnet." Stack you can borrow (FastAPI + MapLibre + APScheduler). Not a methodology source. |

**Allowed use**: a single footnote in the introduction noting that public-facing OSINT dashboards exist (Shadowbroker, WorldMonitor) but lack published methodology — motivating the need for a methodologically grounded approach.

---

## Step 7 — Citation template snippets

Paste-ready BibTeX-ish entries for your reference manager:

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

---

## Reading priority (if you read nothing else)

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
[oberg-yilmaz]: https://journals.sagepub.com/doi/10.1177/20531680251362440
[gdelt-data]: https://www.gdeltproject.org/data.html
[gdelt-mdpi]: https://www.mdpi.com/2306-5729/10/10/158
[gdelt-pvg]: https://politicalviolenceataglance.org/2014/02/20/raining-on-the-parade-some-cautions-regarding-the-global-database-of-events-language-and-tone-dataset/
[gdelt-original]: http://data.gdeltproject.org/documentation/ISA.2013.GDELT.pdf
[icews-comparison]: https://acleddata.com/sites/default/files/wp-content-archive/uploads/2022/02/ACLED_WorkingPaper_ComparisonAnalysis_2019.pdf
[cameo-codebook]: http://eventdata.parusanalytics.com/data.dir/cameo.html
[acled]: https://acleddata.com/
[acled-cast]: https://acleddata.com/conflict-alert-system/
[usgs-quakes]: https://earthquake.usgs.gov/earthquakes/feed/
[nasa-firms]: https://firms.modaps.eosdis.nasa.gov/
[open-meteo]: https://open-meteo.com/
[fsi-methodology]: https://fragilestatesindex.org/methodology/
[finbert-original]: https://arxiv.org/abs/1908.10063
[finbert-arxiv]: https://arxiv.org/pdf/2412.06837
[finbert-finetune]: https://www.mdpi.com/2079-9292/14/23/4680
[instability-arxiv]: https://arxiv.org/abs/2411.06639
[worldmonitor-repo]: https://github.com/koala73/worldmonitor
[shadowbroker-repo]: https://github.com/BigBodyCobain/Shadowbroker
