# OSINT World Monitor — Master Plan

*Working title. The system you build here is the foundation for both your MSc thesis (PX5928, "Open-Source Intelligence and Early-Warning Dashboard") and a personal infrastructure project intended to run for years. This document covers the full path: Pi setup, architecture, the thesis-scoped build, and the long-term roadmap beyond it.*

---

## 0. The vision — what this looks like when it's working

A self-hosted dashboard, reachable from anywhere, showing a world map with toggleable layers. At minimum: financial market sentiment (your existing Market Terminal engine), geopolitical event intensity from GDELT, and active disaster/climate alerts. Sitting above all three, a single composite score, your version of WorldMonitor's "Country Instability Index", updated continuously and tracked over time. When that score crosses a threshold for a region you care about, you get a Telegram message on your phone, sometimes hours before it would show up as a headline.

Underneath, a Raspberry Pi runs the ingestion and scoring continuously, writing to a database that has been accumulating since the day you started it. Six months from now that's six months of labelled, timestamped, multi-source risk data, a dataset nobody else has, because nobody else has been running this specific combination of sources with this specific scoring method since this date.

The thesis is a snapshot of this system: how it's built, what the composite score is, how it compares to existing literature on instability indices, and what it found over the weeks it was running. The system itself keeps going afterward. The modules you don't get to this summer (aviation, maritime, satellites, the rest of the Shadowbroker/WorldMonitor catalogue) become the roadmap for the years after.

---

## 1. Architecture — the pattern

Both reference projects converge on the same shape, and it's a good one:

- **Frontend**: Next.js, map-based (MapLibre GL or similar), with toggleable layers per domain. This is a natural extension of your existing Market Terminal frontend.
- **Backend**: FastAPI (Python), organised as one module per *domain* (finance, geopolitical, climate, ...). Each domain module owns its own config (what sources/entities it tracks), its own ingestion logic, and its own scoring logic.
- **Storage**: a single database (start with SQLite, can move to Postgres later) holding raw ingested records plus computed scores, append-only by design, this is your growing dataset.
- **Scheduling**: each domain module runs on its own schedule (financial news hourly, GDELT every 15-30 min, disaster feeds hourly) via systemd timers.
- **Correlation layer**: a separate module that reads the latest scores from every domain and computes the composite index. This is what makes it an "early warning dashboard" rather than just four separate dashboards bolted together, and it's the centrepiece of your thesis methodology.
- **Alerting**: a lightweight watcher that checks the composite score (and individual domain scores) against thresholds and pushes to Telegram.

You already own most of the hard parts of domain A (finance). Domains B and C are new but use well-documented free APIs. The correlation layer is new work, but conceptually simple, a weighted combination of normalised scores, this is genuinely good Master's-level methodology, especially if you compare your weighting choices against how WorldMonitor's CII or the Buldú et al. football network papers justify their parameter choices.

---

## 2. Two paths: standalone vs HomeForge spoke

You asked to see both. Here they are, with a recommended progression rather than a hard either/or.

### Path A — Standalone

The Pi runs its own complete stack: Docker + Docker Compose, its own SQLite (or Postgres container), its own lightweight reverse proxy (Caddy is simpler than Traefik for a single-purpose box), and its own Tailscale identity purely for remote SSH access. LLM calls (FinBERT sentiment, any summarisation) continue exactly as Market Terminal does now, your existing idempotent caching keeps costs near zero.

**Why this first**: zero risk to HomeForge while you're under thesis pressure. If something breaks at 1am two days before the presentation, the blast radius is one Pi, not your entire homelab. Fully self-contained, easy to document in the thesis ("the system runs on a dedicated Raspberry Pi"), easy to demo, easy to wipe and restart if you need to.

### Path B — HomeForge spoke

The Pi joins your existing Tailscale tailnet as a new spoke. Traefik on the HomeForge hub gets a routing rule for the dashboard (matching your existing `*.nip.io` pattern). The backend writes to a new schema on HomeForge's existing Postgres instance, which means it inherits your existing Restic backup sidecar automatically, your growing dataset gets backed up for free. NLP tasks (sentiment, summarisation) call HomeForge's Ollama instance over the tailnet instead of an external API, fully local-first, zero marginal cost, and the Pi itself becomes a lighter-weight ingestion/edge node since the heavy model inference happens on the more powerful hub.

**Why this second**: architecturally better long-term (free backups, free local inference, unified access), but it means making changes to a homelab that's currently stable and serving other things (Nextcloud, Matrix, etc.) right when you can least afford an outage.

### Recommended progression

Build on Path A for the first 3-4 weeks, get the financial and GDELT modules running reliably, get the presentation done. Once the core pipeline is proven and you're past the immediate deadline pressure, migrate to Path B: join the tailnet, point the database connection string at HomeForge's Postgres, swap the LLM endpoint to Ollama. Each of those is a small, isolated change you can do one at a time, with the standalone version as a fallback if anything goes wrong.

---

## 3. Raspberry Pi setup (Phase 0)

### 3.1 First, check what you actually have

Before anything else, SSH into a fresh boot (or boot Pi OS Lite once with a keyboard attached) and run:

```bash
cat /proc/cpuinfo | grep Model
free -h
lsblk
```

This tells us the Pi model (affects how comfortable FinBERT inference is, a Pi 4/4GB+ or any Pi 5 is fine for hourly batches; a Pi 3 or Zero 2W can still do it but with smaller batches and longer windows), available RAM, and what drives are visible once you plug in the hard drives you mentioned.

### 3.2 Flash the OS

Raspberry Pi OS Lite, 64-bit. Use Raspberry Pi Imager on your laptop, not a desktop environment, you don't need one and it just consumes RAM. In the Imager's advanced options (gear icon / Ctrl+Shift+X), set:

- hostname (suggest `osint-node` or similar, something that reads cleanly in `tailscale status` later)
- enable SSH, paste your public key (no password auth from day one)
- set locale/timezone

### 3.3 Storage layout

OS lives on the microSD card. All application data (database, Docker volumes, logs) lives on one of your external hard drives, connected via USB. This is the single most important reliability decision for a "runs for years" system, SD cards degrade under sustained write loads, and you do not want your multi-month dataset to evaporate because of a worn-out card.

After first boot:

```bash
lsblk                          # identify the external drive, e.g. /dev/sda1
sudo mkdir /mnt/data
sudo mount /dev/sda1 /mnt/data
# add to /etc/fstab for persistence across reboots
```

Everything in the project (database file, Docker volume mounts) points at `/mnt/data/...` from here on.

### 3.4 Base software

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y docker.io docker-compose-plugin git python3-venv
sudo usermod -aG docker $USER
```

A hardware watchdog is worth enabling now while you're in the config, so the Pi auto-reboots if it ever hangs unattended:

```bash
sudo apt install -y watchdog
# enable in /etc/watchdog.conf, set watchdog-device and max-load
sudo systemctl enable watchdog
```

### 3.5 Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

From this point on, every remaining step can be done from Edinburgh, Aberdeen, or anywhere else, SSH over Tailscale works identically regardless of network.

### 3.6 Repo and project skeleton

Following your existing 1:1:1 workflow conventions, create a new repo (e.g. `osint-world-monitor`). Suggested skeleton:

```
osint-world-monitor/
├── backend/
│   ├── domains/
│   │   ├── finance/        # ported from news-intelligence-platform
│   │   ├── geopolitical/    # GDELT
│   │   └── climate/         # disaster/weather
│   ├── correlation/          # composite index
│   ├── alerting/             # Telegram bot
│   └── api/                  # FastAPI app tying it together
├── frontend/                  # Next.js, extends Market Terminal UI
├── data/                       # gitignored, points at /mnt/data
├── docker-compose.yml
└── docs/
    └── thesis/                # working notes that become the report
```

Clone this onto the Pi, set up a Python venv under `backend/`, and you're ready for Phase 1.

---

## 4. The modules (Phase 1 — thesis scope)

Four modules. The first three feed data in; the fourth synthesises and alerts. This is the scope for the thesis, deliberately smaller than the 60-feed reference projects, focused and defensible beats broad and shallow for a Master's report.

### Module A — Financial risk (porting Market Terminal)

| | |
|---|---|
| **Source** | Your existing news-intelligence-platform pipeline: financial news ingestion, FinBERT sentiment, TF-IDF clustering, NER |
| **What changes** | Mostly environment migration. Move the ingestion + scoring scripts onto the Pi, wrap as a systemd timer (hourly), point output at the shared database instead of (or in addition to) wherever it currently writes |
| **New work** | Confirm your existing Geopolitical Risk Index engine, audit what it currently ingests. If it already pulls GDELT or similar, Module B below may be largely done already and just needs porting + extending rather than building fresh |
| **Storage** | `finance_articles` (raw + sentiment score + entities + timestamp), `finance_daily_score` (aggregated per-day, per-sector or per-region) |
| **Frontend layer** | Map markers/regions coloured by financial sentiment, time-series chart of the aggregate score |

### Module B — Geopolitical risk (GDELT)

| | |
|---|---|
| **Source** | [GDELT GKG 2.0](https://www.gdeltproject.org/data.html), updated every 15 minutes, downloadable as CSV files, no API key required for the raw feed |
| **Ingestion** | Pull latest GKG file every 15-30 min, filter to themes relevant to instability (conflict, political turmoil, economic crisis themes are tagged in GDELT's theme taxonomy), aggregate "tone" and event count per country/day |
| **Storage** | `gdelt_events` (raw filtered records), `gdelt_daily_score` (per-country tone + event volume) |
| **Frontend layer** | Country-level choropleth or markers, coloured by tone/event intensity |
| **Note** | This directly satisfies the "not a single data source" requirement in the project brief, and gives you a genuinely independent signal to correlate against Module A |

### Module C — Disaster and climate early warning

| | |
|---|---|
| **Sources** | [USGS Earthquake API](https://earthquake.usgs.gov/earthquakes/feed/) (free, no key, real-time GeoJSON), [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (active fire/hotspot data, free API key via NASA Earthdata), [Open-Meteo](https://open-meteo.com/) (severe weather alerts, free, no key) |
| **Ingestion** | Each source has a simple REST/JSON endpoint, poll hourly, store events above a magnitude/severity threshold |
| **Storage** | `disaster_events` (type, location, severity, timestamp) |
| **Frontend layer** | Markers for active fires, recent significant earthquakes, severe weather warnings |
| **Why this matters academically** | This is your "weather alerts" requirement satisfied with minimal complexity, and it's a third *independent* signal type (physical/environmental, vs financial and political), which makes the correlation layer genuinely interesting rather than two flavours of the same thing |

### Module D — Composite early-warning index + alerting

This is the academic core. For each tracked region, combine the normalised scores from A, B, and C into a single index, your equivalent of WorldMonitor's Country Instability Index, but with your own weighting and justification, which is exactly the kind of methodological choice a thesis examiner wants to see you defend.

Start simple and defensible: z-score normalise each domain's daily score, combine via a weighted sum (equal weights as a baseline, then optionally explore whether weighting by historical correlation with known events improves things, this is good "results" material). Track the composite score over time per region.

**Alerting**: a script checks the composite score against a threshold every time it updates. On breach, send a Telegram message via the [Telegram Bot API](https://core.telegram.org/bots/api) (free, a few lines of Python). This is also your most demoable feature, a phone notification during your presentation lands well.

| | |
|---|---|
| **Storage** | `composite_scores` (region, date, component scores, combined score) |
| **Frontend layer** | The headline number/chart on the dashboard, plus an alert log |

---

## 5. Dashboard

Extends your existing Market Terminal Next.js frontend rather than replacing it. Add a map view (MapLibre GL is free and well-documented, same library Shadowbroker uses) with layer toggles for each module, plus a sidebar showing the composite index per region and recent alerts. For the 22nd June presentation, this doesn't need to be polished, it needs to show real data flowing from a real running system. Polish comes later.

---

## 6. Mapping to the thesis

The 4,000-word main report maps onto this system fairly directly:

| Thesis section | Content |
|---|---|
| **Introduction** | Background on OSINT/early-warning systems, instability indices in the literature (WorldMonitor's CII, academic instability index papers), how passive news monitoring (your starting point) differs from active multi-source early warning |
| **Data** | Describe the three source types (financial news, GDELT, disaster feeds), volumes, time ranges covered by your running system |
| **Methods** | FinBERT sentiment methodology (you can reuse/adapt explanation from your existing project), GDELT filtering/aggregation approach, normalisation and composite scoring methodology, alerting threshold logic |
| **Results** | Time-series of the composite score for selected regions, case studies where a spike in the composite preceded a real-world event covered in the news (this is your strongest result if you can find even one or two clean examples), comparison of your composite's behaviour against any single component alone |
| **Discussion** | How your approach compares to WorldMonitor's CII and to the academic literature on early-warning/instability indices, limitations (number of sources, time window, weighting choices), future work, this is where the unbuilt modules (Section 9 below) go explicitly |
| **Supplementary material** | All code, well-commented, runnable, this is your actual repo |

Getting the system running continuously as early as possible matters a lot here, the Results section is only as good as the data you've accumulated by the time you write it. Every week the pipeline runs from now is a week of real data for Results.

---

## 7. Ten-week timeline (15 June → 28 August)

| Week | Dates | Focus |
|---|---|---|
| 1 | 15-21 Jun | Pi setup (Section 3), port Module A (financial), get it running on a schedule. Goal: real data flowing before the presentation |
| 2 | 22-28 Jun | **Presentation week (slides due 22nd)**. In parallel, start Module B (GDELT) |
| 3 | 29 Jun-5 Jul | Finish Module B, start Module C (disaster/climate) |
| 4 | 6-12 Jul | Finish Module C, start Module D (composite index + Telegram alerting) |
| 5 | 13-19 Jul | Finish Module D. Dashboard pass, add map view with layer toggles. **System should be fully running end-to-end by end of this week**, every subsequent week adds to your dataset |
| 6 | 20-26 Jul | Begin writing: Introduction, Data, Methods sections, drawing on literature (WorldMonitor docs, GDELT papers, instability index literature, the football-network papers' approach to justifying parameters is a useful structural template) |
| 7 | 27 Jul-2 Aug | Results section: pull accumulated data, generate figures, look for case studies (composite spikes vs real events) |
| 8 | 3-9 Aug | Discussion/Conclusion, literature comparison. **Send first full draft to Marco** with time for feedback |
| 9 | 10-16 Aug | Incorporate feedback, refine figures and writing |
| 10 | 17-23 Aug | Final polish, supplementary material cleanup (code comments, README), word count check |
| Buffer | 24-28 Aug | Submission |

If you've migrated to Path B (HomeForge spoke), the natural window is weeks 6-8, once the pipeline is proven and you're in writing mode rather than active feature development, so a brief outage while reconfiguring doesn't cost you data-collection time.

---

## 8. Group presentation note

Your individual section (2-2.5 min) can present Module A specifically (financial risk, your head-start, easiest to show concrete preliminary results from week 1) as your contribution to the shared "early-warning dashboard" concept the group intro establishes. If your groupmates are building geopolitical or supply-chain modules, your composite index in Module D is naturally where all three could converge later, worth a one-line mention in the "how our ideas connect" closing section the group discussed, even if the actual integration isn't built yet.

---

## 9. Decade roadmap (Phase 2 and beyond)

This is the backlog. None of this is needed for the thesis, but it's where the system goes afterward, and it's legitimate "future work" material for the Discussion section. Roughly in order of how cleanly they extend the existing architecture:

- **Aviation tracking** ([OpenSky Network](https://opensky-network.org/), free ADS-B data) — military/government aircraft movement as a geopolitical signal, mirrors Shadowbroker's approach
- **Maritime tracking** (AIS vessel data) — shipping/supply-chain disruption signals
- **Cyber threat feeds** (abuse.ch Feodo Tracker, URLhaus, both free) — adds a cyber dimension to the composite index
- **Supply-chain risk overlay** — cross-reference semiconductor/battery fab locations against Module C's disaster events, directly extends existing infrastructure
- **Satellite tracking** (SatNOGS, free) — space domain awareness
- **Additional languages/regions** — broaden GDELT and news coverage beyond English-language sources
- **Public-facing variant** — once stable, a public read-only dashboard (à la `finance.worldmonitor.app`) becomes a strong portfolio centrepiece, and a natural seed for "decide monetisation later", a paid API tier for the composite index data is the most obvious model if you go that route

---

## 10. Naming

Worth giving this its own identity rather than "the Pi thing", fits your pattern with HomeForge/deerflow/Felix. No pressure to decide now, but when you do, it propagates into the repo name, hostname, and eventually a subdomain. Park it, revisit once the system is actually running and has a personality.

---

## Appendix — key reference links

- GDELT data: https://www.gdeltproject.org/data.html
- USGS earthquake feeds: https://earthquake.usgs.gov/earthquakes/feed/
- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/
- Open-Meteo: https://open-meteo.com/
- Telegram Bot API: https://core.telegram.org/bots/api
- Reference project (architecture/category catalogue): https://github.com/koala73/worldmonitor
- Reference project (stack closest to yours): https://github.com/BigBodyCobain/Shadowbroker
