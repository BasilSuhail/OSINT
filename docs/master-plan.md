# OSINT World Monitor — Master Plan (Revised)

*Working title. The system you build here is the foundation for both your MSc thesis (PX5928, "Open-Source Intelligence and Early-Warning Dashboard") and a personal infrastructure project intended to run for years.*

**Revision note**: this version applies the methodology critique. Major changes: Module C demoted from composite, evaluation pivoted to historical data, JRC-handbook composite scoring, proper academic baselines (ViEWS / FSI / ACLED) replacing WorldMonitor as the comparator. See [`literature-baseline.md`](literature-baseline.md) for the required citations and [`evaluation-protocol.md`](evaluation-protocol.md) for the pre-registered evaluation methodology.

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

A self-hosted dashboard, reachable from anywhere, showing a world map with toggleable layers: financial news sentiment (your Market Terminal pipeline, ported), geopolitical event intensity from GDELT (deduplicated, CAMEO-filtered), and a composite stress index per country. Above all three, a defensible composite score grounded in the [OECD/JRC composite indicator methodology][jrc-handbook], evaluated against [ACLED][acled]-labelled historical events, with [Pushover][pushover-api] notifications on threshold breach.

The Pi runs ingestion and scoring continuously. The thesis is a methodology and retrospective evaluation paper, not a "look at our running system" demo — the literature on conflict early-warning ([ViEWS][views-paper], [ICEWS][icews-comparison], [Goldstone PITF][goldstone-pitf]) uses years of historical data, and so do you.

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

### Module A — Financial news sentiment (porting Market Terminal)

| | |
|---|---|
| **Source** | Existing [news-intelligence-platform](https://github.com/BasilSuhail) pipeline: financial news ingestion, FinBERT sentiment, TF-IDF clustering, NER |
| **Framing** | Call it "financial **news** sentiment" everywhere. FinBERT predictive validity for prices is documented as low (R²≈0.01) — see [Predicting Stock Prices with FinBERT-LSTM (arXiv 2412.06837)][finbert-arxiv]. Do **not** claim it predicts markets. It's one signal of news framing tone toward sectors/regions. |
| **Changes** | Port scripts to Pi, wrap as systemd timer (hourly), write to shared `events` table |
| **Storage** | `events` (with `source='finance'`), aggregated `finance_daily_score` per country |
| **Frontend** | Map markers/regions coloured by sentiment, time-series |

### Module B — Geopolitical events (GDELT, deduplicated)

| | |
|---|---|
| **Source** | [GDELT GKG 2.0][gdelt-data], every 15 min, no API key |
| **Critical step** | **Mandatory deduplication and CAMEO theme filtering** before scoring. Raw GDELT has documented ~55% key field accuracy and ~20% redundancy ([MDPI 2025][gdelt-mdpi], [Political Violence at a Glance][gdelt-pvg]). Use CAMEO codebook ([Schrodt][cameo-codebook]) to filter conflict / political turmoil / economic crisis themes. |
| **Score** | Aggregate event count + Goldstein-scale weighted intensity per country-day. Use Goldstein, **not** raw tone — tone construct validity is contested. |
| **Storage** | `events` (with `source='gdelt'`), `gdelt_daily_score` |
| **Frontend** | Country choropleth coloured by event intensity |

### Module C — Disaster / climate dashboard layer (NOT in composite)

| | |
|---|---|
| **Sources** | [USGS Earthquake API][usgs-quakes], [NASA FIRMS][nasa-firms], [Open-Meteo][open-meteo] |
| **Role** | Dashboard layer + alerting only. **Excluded from the composite index** — earthquakes and fires are exogenous shocks, not leading indicators of political/financial instability at weekly timescales. Including them in the composite would inject spurious noise (a Japan earthquake → composite spike → "Japan unstable?" with no defence). |
| **Use as null control** | Optional secondary analysis — does your composite *not* react to earthquake events? Good robustness check. |
| **Storage** | `events` (with `source='disaster'`), `disaster_events` |
| **Frontend** | Markers for active fires, significant earthquakes, severe weather |

### Module D — Composite stress index (JRC-handbook methodology)

The academic core. Built per [OECD/JRC Handbook on Constructing Composite Indicators][jrc-handbook] — this is the standard reference and what an examiner will compare your methodology against.

**Steps (JRC structure)**:

1. **Theoretical framework** — declare which indicators belong together and why. Two domains: financial news sentiment (Module A) + geopolitical event intensity (Module B). Justification: both reflect public information environment for instability; both are commonly used in conflict / sovereign-risk forecasting literature ([ViEWS][views-paper], [Goldstone PITF][goldstone-pitf]).
2. **Multivariate analysis** — correlation structure between A and B, PCA loading inspection. If A and B are too correlated, the composite is redundant; if too uncorrelated, they may be measuring different things.
3. **Normalisation** — z-score across rolling window (defensible vs min-max because outliers matter). Document the rolling window choice with sensitivity analysis.
4. **Weighting** — start equal-weighted (default JRC choice when no prior). Then **sensitivity analysis** across alternative weights (PCA-derived, equal, single-signal-dominant).
5. **Aggregation** — linear weighted sum baseline. Optionally geometric mean as robustness alternative (less compensability — a country can't fully offset bad finance with good politics).
6. **Robustness** — bootstrap confidence intervals, Monte Carlo over weight perturbations. Does country ranking change?
7. **Alerting** — threshold on composite → [Pushover][pushover-api] notification. Threshold chosen via ROC analysis on historical labelled events.

**Storage**: `composite_scores` (country, date, component scores, combined score, percentile)

### Module E — Evaluation (historical, pre-registered)

This is what makes the thesis defensible. See [`evaluation-protocol.md`](evaluation-protocol.md) for the full pre-registered protocol.

**Summary**:

- **Ground truth**: [ACLED][acled] event data (peer-reviewed, human-validated, free for academic use). Pre-specified event types: armed conflict onset, mass protest, civil unrest escalation.
- **Time period**: historical evaluation on GDELT archive (back to 2015) + ACLED labels, country-month panel.
- **Metrics**: AUROC, AUPR, Brier score (standard in conflict forecasting per [ViEWS comparison review][cews-review]).
- **Baselines**: (1) persistence model (yesterday's score), (2) single-signal (finance only, GDELT only), (3) the composite.
- **Question**: does the composite beat each baseline at AUROC/AUPR?
- **Detection delay**: distribution of lead time (composite breach → ACLED-confirmed event), reported as median + IQR.
- **Pi prospective data**: live demo only. Not the primary evaluation.

---

## 5. Dashboard

Next.js + MapLibre GL, extends Market Terminal frontend. Layer toggles per module, sidebar with composite per region + recent alerts. For the 22 June presentation: needs real data flowing from a real running system, not polish.

---

## 6. Thesis mapping

| Section | Content | Word budget (target) |
|---|---|---|
| Abstract | 300 words separate | — |
| Introduction + literature | OSINT/EWS background, ViEWS/FSI/ICEWS comparison, gap statement | ~700 |
| Data | GDELT (with quality caveats), ACLED, financial news corpus | ~500 |
| Methods | JRC composite methodology, deduplication pipeline, FinBERT + Goldstein, evaluation protocol | ~1,200 |
| Results | Composite vs baselines (AUROC/AUPR/Brier), detection delay analysis, case-study narratives, sensitivity analysis | ~900 |
| Discussion | Limitations (FinBERT validity, GDELT noise, ground-truth gaps), industrial applications, future work | ~400 |
| **Total** | | **4,000** |

The Results section is only as good as historical data + ground truth permit. The Pi's accumulated prospective data is a **demonstration**, not the evaluation.

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

Individual section (2-2.5 min): present Module A specifically as your contribution. If groupmates build geopolitical or supply-chain modules, the **shared `events` schema** is the natural integration point — raise this in week 1 so all three modules write to a compatible table from day one. If schema-sharing politically fails, drop the group integration framing in your individual thesis writing and present as a solo project under shared theme.

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
