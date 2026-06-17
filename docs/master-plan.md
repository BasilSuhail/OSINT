# OSINT World Monitor — Master Plan (Revised)

*Working title. The system you build here is the foundation for both your MSc thesis (PX5928, "Open-Source Intelligence and Early-Warning Dashboard") and a personal infrastructure project intended to run for years.*

**Revision note (multi-modal re-anchor)**: thesis lens shifted from finance-anchored to **multi-modal OSINT composite** (geopolitical + market + disaster/hazard). Driven by the PX5901/02 guidelines confirming the thesis is individual work (group structure applies only to the oral presentation), which removes the constraint that the individual thesis must mirror the group-presentation finance lane. Module C is **promoted** back into the composite as the disaster/hazard domain. The earlier methodology critique (JRC handbook, ACLED ground truth, AUROC/AUPR/Brier evaluation, mandatory GDELT deduplication, FinBERT honesty) all carries over unchanged. See [`literature-baseline.md`](literature-baseline.md) for the required citations and [`evaluation-protocol.md`](evaluation-protocol.md) for the pre-registered evaluation methodology.

---

## Quick navigation

- [0. Vision](#0-vision)
- [1. Architecture](#1-architecture)
- [2. Standalone vs HomeForge spoke](#2-standalone-vs-homeforge-spoke)
- [3. Raspberry Pi setup (Phase 0)](#3-raspberry-pi-setup-phase-0)
- [4. Modules (Phase 1 — thesis scope)](#4-modules-phase-1--thesis-scope)
- [5. Dashboard](#5-dashboard)
- [6. Thesis mapping](#6-thesis-mapping)
- [7. Ten-week timeline](#7-ten-week-timeline)
- [8. Group presentation note](#8-group-presentation-note)
- [9. Decade roadmap](#9-decade-roadmap)
- [10. Naming](#10-naming)
- [Appendix — reference links](#appendix--reference-links)

---

## 0. Vision

A self-hosted dashboard, reachable from anywhere, showing a world map with toggleable layers across three input domains plus situational-awareness Layer 3 feeds:

- **Geopolitical** — GDELT v2 events (deduplicated, CAMEO-filtered, Goldstein-weighted)
- **Market / macro** — yfinance + FRED (vol, FX, yields, macro); FinBERT-on-news as an optional auxiliary signal
- **Disaster / hazard** — USGS Quake + GDACS multi-hazard + NASA FIRMS fires

Above the three domains, a defensible **multi-modal composite stress index** per country, grounded in the [OECD/JRC composite indicator methodology][jrc-handbook] and evaluated against a hybrid ground truth ([ACLED][acled] conflict events + market-crisis dates), with [Pushover][pushover-api] notifications on threshold breach.

The Pi runs ingestion and scoring continuously. The thesis is a methodology and retrospective evaluation paper, not a "look at our running system" demo — the literature on conflict early-warning ([ViEWS][views-paper], [ICEWS][icews-comparison], [Goldstone PITF][goldstone-pitf]) uses years of historical data, and so do you. Layer 3 feeds (satellites, news RSS, aviation, maritime, weather, off-grid mesh — full list in [`architecture/01-overview.md`](architecture/01-overview.md#feed-taxonomy)) are dashboard breadth, not composite inputs.

---

## 1. Architecture

- **Frontend**: Next.js + MapLibre GL, extends your existing Market Terminal frontend
- **Backend**: FastAPI (Python), one module per *domain* (finance, geopolitical, disaster), each owning its config, ingestion, scoring
- **Storage**: single database (SQLite → Postgres later), append-only, common `events` table per Marco's brief (fields: `time, location, source, category, severity, keywords, confidence`)
- **Scheduling**: systemd timers per module (finance hourly, GDELT every 30 min, disaster hourly)
- **Composite layer**: separate module reading latest scores per domain, computing composite index per [JRC handbook][jrc-handbook] structure (normalisation → weighting → aggregation → sensitivity analysis)
- **Alerting**: lightweight watcher → Pushover REST on threshold breach

Reference projects ([WorldMonitor][worldmonitor-repo], [Shadowbroker][shadowbroker-repo]) are architectural inspiration only — neither has peer-reviewed methodology, so they do **not** appear in the thesis literature review.

---

## 2. Standalone vs HomeForge spoke

### Path A — Standalone

The Pi runs its own complete stack: Docker, SQLite (or Postgres container), Caddy reverse proxy, Tailscale for SSH. LLM calls (FinBERT) continue as Market Terminal does now.

Why first: zero risk to HomeForge under thesis pressure; if something breaks at 1am two days before submission, blast radius is one Pi.

### Path B — HomeForge spoke

Pi joins Tailscale tailnet as new spoke. Traefik on HomeForge gets a routing rule. Backend writes to a new schema on HomeForge's Postgres → inherits Restic backup. FinBERT inference moves to HomeForge's Ollama → fully local, zero marginal cost.

Why second: architecturally better long-term but changes a stable homelab when you can least afford an outage.

### Recommended progression

**Path A for thesis.** Path B is post-submission. Do not migrate during writing weeks. (Revised from earlier plan — Section 7 timeline removed the HomeForge migration window entirely.)

---

## 3. Raspberry Pi setup (Phase 0)

### Step 3.1 — Hardware audit

```bash
cat /proc/cpuinfo | grep Model
free -h
lsblk
```

Pi 4 (4GB+) or Pi 5 → fine for hourly FinBERT batches. Pi 3 / Zero 2W → smaller batches, longer windows.

### Step 3.2 — Flash OS

Raspberry Pi OS Lite, 64-bit. In Imager advanced options (Ctrl+Shift+X):

- hostname (`osint-node` or similar)
- enable SSH, paste your public key (no password auth)
- locale/timezone

### Step 3.3 — Storage layout

OS on microSD. All application data (DB, Docker volumes, logs) on external USB drive. Non-negotiable for a multi-year system — SD cards die under sustained writes.

```bash
lsblk                          # identify external drive, e.g. /dev/sda1
sudo mkdir /mnt/data
sudo mount /dev/sda1 /mnt/data
# add to /etc/fstab for persistence
```

Everything in the project points at `/mnt/data/...`.

### Step 3.4 — Base software

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y docker.io docker-compose-plugin git python3-venv watchdog
sudo usermod -aG docker $USER
sudo systemctl enable watchdog
```

### Step 3.5 — Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### Step 3.6 — Project skeleton

```
osint-world-monitor/
├── backend/
│   ├── domains/
│   │   ├── finance/        # ported from news-intelligence-platform
│   │   ├── geopolitical/    # GDELT
│   │   └── disaster/        # optional dashboard layer, not in composite
│   ├── composite/            # JRC-handbook composite indicator
│   ├── evaluation/           # ACLED ground-truth, AUROC/AUPR/Brier
│   ├── alerting/             # Pushover
│   └── api/                  # FastAPI
├── frontend/                  # Next.js + MapLibre GL
├── data/                       # gitignored, points at /mnt/data
├── docker-compose.yml
└── docs/
    └── thesis/
```

---

## 4. Modules (Phase 1 — thesis scope)

Three modules feed data in; one synthesises; one evaluates. Scope deliberately smaller than 60-feed reference projects. Marco's brief says "small-scale" — focused beats broad.

**Shared schema**: every module writes into a common `events` table with fields `time, location, source, category, severity, keywords, confidence`. This is Marco's explicit specification — single schema is what enables the composite.

### Module A — Market signals (yfinance + FRED + optional FinBERT)

| | |
|---|---|
| **Sources** | [`yfinance`](https://github.com/ranaroussi/yfinance) (equities, indices, FX, crypto, ETF flows), [FRED](https://fred.stlouisfed.org/docs/api/fred/) (CPI, unemployment, GDP, yield curves), optional FinBERT-on-news using the existing news-intelligence-platform pipeline |
| **Framing** | Market-stress component of the composite. Per-country signals where possible (equity index drawdown, sovereign-yield blowout, FX depreciation, vol spike). FinBERT is **auxiliary**, not the anchor: predictive validity for downstream prices is documented as low (R²≈0.01) — see [Predicting Stock Prices with FinBERT-LSTM (arXiv 2412.06837)][finbert-arxiv]. Used as a news-tone signal, not a price predictor. |
| **Changes** | Wrap as Celery worker (`worker-finance`), 5-min fast tier; write to shared `events` table |
| **Storage** | `events` (with `source='yfinance'` / `source='fred'` / `source='finbert-rss'`), aggregated `market_daily_score` per country |
| **Frontend** | Map markers/regions coloured by market-stress component, time-series per signal |

### Module B — Geopolitical events (GDELT, deduplicated)

| | |
|---|---|
| **Source** | [GDELT GKG 2.0][gdelt-data], every 15 min, no API key |
| **Critical step** | **Mandatory deduplication and CAMEO theme filtering** before scoring. Raw GDELT has documented ~55% key field accuracy and ~20% redundancy ([MDPI 2025][gdelt-mdpi], [Political Violence at a Glance][gdelt-pvg]). Use CAMEO codebook ([Schrodt][cameo-codebook]) to filter conflict / political turmoil / economic crisis themes. |
| **Score** | Aggregate event count + Goldstein-scale weighted intensity per country-day. Use Goldstein, **not** raw tone — tone construct validity is contested. |
| **Storage** | `events` (with `source='gdelt'`), `gdelt_daily_score` |
| **Frontend** | Country choropleth coloured by event intensity |

### Module C — Hazards / disaster (promoted to composite input)

| | |
|---|---|
| **Sources** | [USGS Earthquake API][usgs-quakes], [GDACS multi-hazard alerts](https://www.gdacs.org/), [NASA FIRMS][nasa-firms] fire hotspots. [Open-Meteo][open-meteo] retained as Layer 3 dashboard weather layer. |
| **Role (re-anchor)** | Now an input to the composite as the **hazard / disaster domain**. Earlier methodology critique objected that earthquakes are exogenous and risk spurious composite spikes; the multi-modal re-anchor accepts this as a *feature*: hazards are an exogenous stressor that interacts with geopolitical and market signals, and the composite's job is to discriminate which combinations precede instability. The risk of spurious spikes is handled at evaluation time — Module E checks whether the composite's response to isolated hazard events without geo/market corroboration is filtered out by the JRC normalisation step. |
| **Engineering** | Per-country aggregated hazard intensity score (fatalities × magnitude weighting for quakes, GDACS alert level, FIRMS hotspot count weighted by population proximity). Computed as a Celery slow-tier task. |
| **Storage** | `events` (with `source='usgs-quake'` / `source='gdacs'` / `source='nasa-firms'`), aggregated `hazard_daily_score` per country |
| **Frontend** | Markers for active fires, significant earthquakes, GDACS alerts; choropleth for hazard component of composite |

### Module D — Composite stress index (JRC-handbook methodology)

The academic core. Built per [OECD/JRC Handbook on Constructing Composite Indicators][jrc-handbook] — this is the standard reference and what an examiner will compare your methodology against.

**Steps (JRC structure)**:

1. **Theoretical framework** — declare which indicators belong together and why. Three domains: market signals (Module A), geopolitical event intensity (Module B), and hazard / disaster intensity (Module C). Justification: all three reflect public observable stress in the country information environment; multi-modal fusion across heterogeneous OSINT modalities is the thesis's research contribution. Domain provenance: financial / sovereign-risk forecasting ([ViEWS][views-paper], [Goldstone PITF][goldstone-pitf]) plus disaster-instability interaction literature.
2. **Multivariate analysis** — correlation structure across A, B, C; PCA loading inspection across three domains. Report whether any pair is too correlated (composite redundant) or too uncorrelated (measuring different latent factors).
3. **Normalisation** — z-score across rolling window per signal (defensible vs min-max because outliers matter). Document the rolling window choice with sensitivity analysis.
4. **Weighting** — start equal-weighted across the three domains (default JRC choice when no prior). Then **sensitivity analysis** across alternative weights (PCA-derived; equal; single-domain-dominant; expert-prior).
5. **Aggregation** — linear weighted sum baseline. Geometric mean as a less-compensatory robustness alternative (so a country can't fully offset bad geopolitics with calm markets and no hazards).
6. **Robustness** — bootstrap confidence intervals, Monte Carlo over weight perturbations from a Dirichlet prior. Does the country ranking change? Does dropping any one of A, B, C collapse the discrimination?
7. **Alerting** — threshold on composite → [Pushover][pushover-api] notification. Threshold chosen via ROC analysis on historical labelled events (per [`evaluation-protocol.md`](evaluation-protocol.md)).

**Storage**: `scores` (country, bucket_start, bucket_length, score_name, score_value, components JSONB with per-domain breakdown, method_version)

### Module E — Evaluation (historical, pre-registered)

This is what makes the thesis defensible. See [`evaluation-protocol.md`](evaluation-protocol.md) for the full pre-registered protocol.

**Summary**:

- **Ground truth (hybrid)**: [ACLED][acled] conflict events + market-crisis dates (NBER recessions, country-level VIX-equivalent spikes > 30, sovereign yield blowouts, IMF currency-crisis dataset). Pre-specified event types per modality, declared before composite output is examined.
- **Time period**: historical evaluation on GDELT archive (back to 2015) + ACLED + market-crisis labels, country-month panel.
- **Metrics**: AUROC, AUPR, Brier score, lead-time distribution (standard in conflict forecasting per [ViEWS comparison review][cews-review]).
- **Baselines**: B0 random, B1 persistence, B2 base rate, B3 geo-only (Module B), B4 market-only (Module A), B5 hazard-only (Module C), B6 equal-weight composite, B7 PCA-weight composite. Composite must beat **each** single-domain baseline on both AUROC and AUPR for the multi-modal claim to hold.
- **Question**: does the multi-modal composite discriminate later instability events better than the best single-domain baseline?
- **Detection delay**: distribution of lead time (composite breach → ground-truth event), reported as median + IQR, per event type.
- **Pi prospective data**: live demo only. Not the primary evaluation.

---

## 5. Dashboard

Next.js + MapLibre GL, extends Market Terminal frontend. Layer toggles per module, sidebar with composite per region + recent alerts. For the 22 June presentation: needs real data flowing from a real running system, not polish.

---

## 6. Thesis mapping

| Section | Content | Word budget (target) |
|---|---|---|
| Abstract | 300 words separate | — |
| Introduction + literature | OSINT/EWS background, ViEWS/FSI/ICEWS comparison, gap statement on multi-modal fusion | ~650 |
| Data | GDELT (with quality caveats), ACLED + market-crisis label sources, yfinance/FRED, USGS/GDACS/FIRMS | ~600 |
| Methods | JRC composite across three domains, deduplication pipeline, Goldstein + market-stress + hazard normalisation, evaluation protocol | ~1,300 |
| Results | Composite vs per-domain and combined baselines (AUROC/AUPR/Brier), detection delay analysis, case-study narratives, sensitivity analysis | ~1,050 |
| Discussion | Limitations (GDELT noise, market-data coverage gaps, hazard-as-exogenous-shock interpretation, ground-truth gaps), industrial applications, future work (Layer 3 feeds) | ~400 |
| **Total** | | **4,000** |

The Results section is only as good as historical data + ground truth permit. The Pi's accumulated prospective data is a **demonstration**, not the evaluation. Layer 3 feeds (satellites, news RSS, aviation, maritime, weather, off-grid) appear only in the Discussion as future-work directions, not in the formal evaluation.

---

## 7. Ten-week timeline (15 June → 28 August)

| Week | Dates | Focus |
|---|---|---|
| 1 | 15-21 Jun | Pi setup, port Module A, **start GDELT historical pull (2015→present)** in parallel |
| 2 | 22-28 Jun | **Presentation week (slides due 22nd)**. Start Module B (live GDELT every 30 min) |
| 3 | 29 Jun-5 Jul | Finish Module B (deduplication + CAMEO filter), start Module C (dashboard layer only) |
| 4 | 6-12 Jul | Module D composite (JRC steps 1-5). Start Module E evaluation harness (ACLED join, AUROC/AUPR/Brier) |
| 5 | 13-19 Jul | Finish Module D (steps 6-7), Pushover wiring. System running E2E. **Lock evaluation protocol with Marco before looking at results.** |
| 6 | 20-26 Jul | Start writing: Intro + Lit review + Data. Run historical evaluation. |
| 7 | 27 Jul-2 Aug | Methods + Results sections. Sensitivity analysis. Case-study selection (pre-specified, not cherry-picked). |
| 8 | 3-9 Aug | Discussion + Conclusion. **Send first full draft to Marco.** |
| 9 | 10-16 Aug | Incorporate feedback, refine figures. |
| 10 | 17-23 Aug | Final polish, supplementary material (code comments, README, replication notes). |
| Buffer | 24-28 Aug | Submission. |

**HomeForge migration is explicitly excluded** from this timeline. Defer to post-submission.

---

## 8. Group presentation note

**Per PX5901/02 guidelines**: the *thesis* is individual work; the *oral presentation* is the group component. Group-presentation lane assignments do not constrain what each student writes in their own thesis.

For the group oral (15 min + 10 Q&A on 23-26 June, slides due 22 June 5pm):

- Shared intro: OSINT / early-warning dashboard framing, common GDELT-as-baseline source
- Your 2-2.5 min individual slot: **multi-modal OSINT composite** — three input domains (geopolitical / market / hazard), JRC methodology, ACLED + market-crisis hybrid ground truth, pre-registered AUROC/AUPR evaluation. This is the same story the thesis defends, in compressed form — no scope expansion between June presentation and August thesis.
- Shared close: how the three group projects connect under the OSINT umbrella

If groupmates would benefit from a shared `events` schema for integration on the dashboard, raise it in Week 1 — the common-table design in [`architecture/04-schema.md`](architecture/04-schema.md) is reusable. Schema-sharing is optional for the individual thesis.

---

## 9. Decade roadmap (post-thesis)

Future-work material for the Discussion section, in roughly the order they cleanly extend the architecture:

- **Aviation tracking** ([OpenSky Network][opensky], free ADS-B) — military/government movement signal
- **Maritime tracking** (AIS vessel data via [aisstream.io][aisstream]) — supply-chain disruption signal (**this** is the supply-chain extension Marco's brief mentions, not Module C)
- **Cyber threat feeds** ([abuse.ch][abuse-ch], CISA KEV) — cyber dimension
- **Supply-chain risk overlay** — cross-reference semiconductor/battery fab locations against disruption events
- **Satellite tracking** ([SatNOGS][satnogs])
- **Additional languages/regions** — beyond English-language sources
- **HomeForge migration** — Path B from Section 2
- **Public-facing variant** — read-only dashboard (à la `finance.worldmonitor.app`), potential paid API tier for composite index data

---

## 10. Naming

Give it its own identity post-launch. No pressure to decide now; propagates into repo name, hostname, subdomain when done. Revisit once running and has a personality.

---

## Appendix — reference links

### Academic baselines (required reading — see [`literature-baseline.md`](literature-baseline.md))
- [ViEWS: A Political Violence Early-Warning System (Hegre et al, 2019)][views-paper]
- [Review and Comparison of Conflict Early Warning Systems (ScienceDirect 2023)][cews-review]
- [Fragile States Index methodology][fsi-methodology]
- [ICEWS / GDELT comparison (ACLED 2019)][icews-comparison]
- [Goldstone PITF — political instability foundational work][goldstone-pitf]
- [OECD/JRC Handbook on Composite Indicators][jrc-handbook]
- [Öberg & Yilmaz 2025 — measurement issues in event data][oberg-yilmaz]

### Data sources
- [GDELT GKG 2.0][gdelt-data]
- [ACLED][acled] + [ACLED CAST forecast system][acled-cast]
- [USGS Earthquake feeds][usgs-quakes]
- [NASA FIRMS][nasa-firms]
- [Open-Meteo][open-meteo]
- [Pushover API][pushover-api]

### Critique / validity papers
- [GDELT accuracy audit (MDPI 2025)][gdelt-mdpi]
- [GDELT tone critique (Political Violence at a Glance)][gdelt-pvg]
- [FinBERT predictive validity issues (arXiv 2412.06837)][finbert-arxiv]
- [Predicting Country Instability — Bayesian + RF on GDELT (arXiv 2411.06639)][instability-arxiv]

### Reference architectures (NOT methodology comparators)
- [WorldMonitor repo][worldmonitor-repo]
- [Shadowbroker repo][shadowbroker-repo]

[views-paper]: https://journals.sagepub.com/doi/full/10.1177/0022343319823860
[cews-review]: https://www.sciencedirect.com/science/article/pii/S0169207023000018
[fsi-methodology]: https://fragilestatesindex.org/methodology/
[icews-comparison]: https://acleddata.com/sites/default/files/wp-content-archive/uploads/2022/02/ACLED_WorkingPaper_ComparisonAnalysis_2019.pdf
[goldstone-pitf]: https://www.tandfonline.com/doi/abs/10.1111/j.1540-5907.2009.00426.x
[jrc-handbook]: https://www.oecd.org/content/dam/oecd/en/publications/reports/2008/08/handbook-on-constructing-composite-indicators-methodology-and-user-guide_g1gh9301/9789264043466-en.pdf
[oberg-yilmaz]: https://journals.sagepub.com/doi/10.1177/20531680251362440
[gdelt-data]: https://www.gdeltproject.org/data.html
[acled]: https://acleddata.com/
[acled-cast]: https://acleddata.com/conflict-alert-system/
[usgs-quakes]: https://earthquake.usgs.gov/earthquakes/feed/
[nasa-firms]: https://firms.modaps.eosdis.nasa.gov/
[open-meteo]: https://open-meteo.com/
[pushover-api]: https://pushover.net/api
[gdelt-mdpi]: https://www.mdpi.com/2306-5729/10/10/158
[gdelt-pvg]: https://politicalviolenceataglance.org/2014/02/20/raining-on-the-parade-some-cautions-regarding-the-global-database-of-events-language-and-tone-dataset/
[finbert-arxiv]: https://arxiv.org/pdf/2412.06837
[instability-arxiv]: https://arxiv.org/abs/2411.06639
[worldmonitor-repo]: https://github.com/koala73/worldmonitor
[shadowbroker-repo]: https://github.com/BigBodyCobain/Shadowbroker
[cameo-codebook]: http://eventdata.parusanalytics.com/data.dir/cameo.html
[opensky]: https://opensky-network.org/
[aisstream]: https://aisstream.io/
[abuse-ch]: https://abuse.ch/
[satnogs]: https://satnogs.org/
