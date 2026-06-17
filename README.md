# OSINT — Multi-modal Early-Warning Dashboard

Self-hosted open-source-intelligence dashboard plus a multi-modal composite stress index per country, evaluated against a hybrid ground truth. MSc thesis project (PX5928, supervised by Marco Thiel, University of Aberdeen) plus a personal infrastructure project meant to run for years.

The thesis defends a **multi-modal composite over three input domains** (geopolitical, market, hazard) following the OECD/JRC composite indicator handbook, evaluated against ACLED + market-crisis + hazard-disruption labels using AUROC / AUPR / Brier / lead-time. The Pi runs ingestion and scoring continuously; the formal evaluation uses historical data.

## Documentation index

- [`docs/requirements.md`](docs/requirements.md) — PX5928 university spec, group context, three-layer scope analysis, deliverable checklist
- [`docs/methodology.md`](docs/methodology.md) — Part A: pre-registered evaluation protocol (ground truth, splits, baselines, metrics, sensitivity, reporting checklist). Part B: literature baseline (citations + reading priority)
- [`docs/architecture/`](docs/architecture/) — How the system is built (7-section spec; sections 01–03 drafted, 04–07 pending)

## At a glance

- **Hardware**: Raspberry Pi 5 (8 GB) + 2x4TB USB3 HDDs in btrfs RAID1
- **Stack**: FastAPI + Celery + Redis + Postgres 16 + Parquet on btrfs + Next.js + MapLibre GL
- **Inspiration (not citation)**: [Shadowbroker](https://github.com/BigBodyCobain/Shadowbroker) for architectural ideas; methodology lineage is OECD/JRC + ViEWS + Davies et al. — see [`docs/methodology.md`](docs/methodology.md)

## Modules (thesis scope)

| Module | Domain | What it does |
|---|---|---|
| **A — Market signals** | Finance / macro | `yfinance` + FRED pulls; optional FinBERT-on-news as auxiliary signal |
| **B — Geopolitical events** | Conflict / unrest | GDELT v2 events + GKG, deduplicated, CAMEO-filtered, Goldstein-weighted |
| **C — Hazards / disaster** | Earth / climate | USGS Quake + GDACS multi-hazard + NASA FIRMS, per-country aggregation |
| **D — Multi-modal composite** | Synthesis | JRC 10-step composite over A + B + C; Pushover alerting on threshold breach |
| **E — Evaluation** | Defence | Pre-registered AUROC / AUPR / Brier vs single-domain baselines and the hybrid ground truth |

Layer 3 feeds (satellites, news RSS, aviation, maritime, weather, off-grid mesh) sit on the dashboard for situational awareness and **do not enter the composite or the formal evaluation**. Full feed taxonomy lives in [`docs/architecture/01-overview.md`](docs/architecture/01-overview.md#feed-taxonomy).

## Ground truth (hybrid)

The composite is multi-modal, so the labels are too:

- **P1–P3 Geopolitical** — ACLED events (armed conflict onset, mass protest escalation, state-based violence intensification)
- **P4 Market** — NBER recessions, IMF currency-crisis dataset, FRED VIX > 30, sovereign yield spikes, equity drawdowns
- **P5 Hazard** — EM-DAT disaster declarations and GDACS red-alerts cross-referenced with sustained composite stress

The primary classification target is **any-positive** across P1–P5; per-domain subtasks are reported as secondary. Full definition in [`docs/methodology.md`](docs/methodology.md#step-2--ground-truth-hybrid-multi-modal).

## Ten-week timeline (15 June → 28 August)

| Week | Dates | Focus |
|---|---|---|
| 1 | 15-21 Jun | Pi 5 + RAID hardware, port market-signal worker, start GDELT historical pull (2015 → present) in parallel |
| 2 | 22-28 Jun | **Presentation slides due 22 Jun 5pm**; group presentation 23-26 Jun. Start GDELT live worker |
| 3 | 29 Jun-5 Jul | Finish Module B (deduplication + CAMEO + Goldstein), start Module C (hazards: USGS + GDACS + FIRMS) |
| 4 | 6-12 Jul | Module D composite (JRC steps 1-5). Start Module E evaluation harness (ACLED + market + EM-DAT label joins, AUROC/AUPR/Brier) |
| 5 | 13-19 Jul | Finish Module D (steps 6-7), Pushover wiring. System running E2E. **Lock evaluation protocol v1.0 with Marco before looking at results.** |
| 6 | 20-26 Jul | Start writing: Intro + Literature + Data. Run historical evaluation. |
| 7 | 27 Jul-2 Aug | Methods + Results sections. Sensitivity analysis. Case-study selection (pre-specified, not cherry-picked). |
| 8 | 3-9 Aug | Discussion + Conclusion. **Send first full draft to Marco.** |
| 9 | 10-16 Aug | Incorporate feedback, refine figures. |
| 10 | 17-23 Aug | Final polish, supplementary material (code comments, README, replication notes). |
| Buffer | 24-28 Aug | Submission. |

## Group presentation note

Per PX5901/02 guidelines, the **thesis is individual work** and the group structure applies only to the **oral presentation**. The June 22 slot presents the multi-modal composite frame in compressed form — same story the August thesis defends, no scope expansion between the two. Slide content lives in [`docs/`](docs/) once drafted.

## Decade roadmap (post-thesis Layer 3)

Future-work material for the Discussion section, in roughly the order they cleanly extend the architecture:

- Aviation tracking (OpenSky + adsb.lol) — movement signal
- Maritime tracking (AISStream) — supply-chain disruption signal
- Satellite tracking (CelesTrak TLE + NASA NEO + JPL SBDB)
- Space weather (NOAA SWPC)
- News RSS bundle (Reuters / AP / BBC / ISW / Bellingcat)
- Off-grid mesh (Meshtastic / APRS / KiwiSDR)
- HomeForge spoke migration (homelab integration, post-submission)
- Public-facing read-only variant + paid API tier for composite index data

## Status

- Architecture spec (`docs/architecture/`) — sections 01-03 drafted and merged; sections 04-07 pending
- Code — not started
- Pi hardware — not yet purchased

## License

(To be added.)
