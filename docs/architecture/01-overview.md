# 01 — Overview

High-level architecture, module map, and feed taxonomy.

- [Architecture diagram](#architecture-diagram)
- [Module map](#module-map)
- [Boundary rules](#boundary-rules)
- [Feed taxonomy](#feed-taxonomy)
- [What this system is NOT](#what-this-system-is-not)

---

## Architecture diagram

```
                    Pi 5 (8 GB)
   ┌─────────────────────────────────────────────────┐
   │                                                  │
   │   ┌──────────┐    ┌──────────┐    ┌──────────┐  │
   │   │ FastAPI  │←───│  Redis   │───→│  Celery  │  │
   │   │ read API │    │ queue +  │    │ workers  │  │
   │   │ (:8000)  │    │ cache    │    │ (fast /  │  │
   │   └────┬─────┘    └──────────┘    │  slow)   │  │
   │        │                          └────┬─────┘  │
   │        ↓                               ↓        │
   │   ┌──────────────────────────────────────────┐  │
   │   │           Postgres 16 (hot)              │  │
   │   │   events / scores / metadata             │  │
   │   └──────────────────────────────────────────┘  │
   │        │                                        │
   │        ↓                                        │
   │   ┌──────────────────────────────────────────┐  │
   │   │   btrfs RAID1  (2x4TB USB3 UAS)          │  │
   │   │   /mnt/data/pg                            │  │
   │   │   /mnt/data/parquet  (cold archive)       │  │
   │   │   /mnt/data/raw      (untouched dumps)    │  │
   │   └──────────────────────────────────────────┘  │
   │                                                  │
   │   Tailscale tunnel + watchdog + Caddy reverse   │
   └─────────────────────────────────────────────────┘
              │
              ↓
       Next.js static build
       (built on dev mac, rsync'd to Pi)
       MapLibre GL frontend
```

Why the frontend builds off-Pi: 8 GB RAM is tight when Postgres, Redis, FastAPI, and Celery workers all run. Node's build step (esp. Next.js 15) eats 1.5–2 GB transiently. Build on the dev mac, rsync the static `out/` directory, serve via Caddy.

---

## Module map

Thesis modules map 1:1 to dedicated Celery queues. Each queue is a separate worker process so a single bad fetcher cannot bring down the system.

| Master-plan module | Worker queue | Fetch tier | Purpose |
|---|---|---|---|
| A — Market signals | `worker-market` | fast (5 min) | yfinance + FRED pulls, optional FinBERT-on-news as auxiliary signal |
| B — Geopolitical events | `worker-gdelt` | slow (15 min) | GDELT v2 export ingest, deduplicated, CAMEO-filtered, Goldstein per country-day |
| C — Hazards / disaster | `worker-hazard` | slow (15 min) | USGS Quake + GDACS multi-hazard + NASA FIRMS fire hotspots, per-country aggregation |
| D — Composite + alerting | `worker-composite` | slow (1 hr) | Builds multi-modal composite stress index across A + B + C, fires Pushover alerts |
| Pushover dispatch | `worker-notify` | event-triggered | Notification fan-out (decoupled so retries don't block composite) |
| Ground-truth labels | `worker-labels` | daily | Pulls ACLED + NBER + IMF currency-crisis + EM-DAT for the hybrid evaluation ground truth |

**Layer 3 (post-thesis additions)** — these add workers, never touch core:

- `worker-flights` (OpenSky + adsb.lol)
- `worker-ships` (AISStream)
- `worker-sat` (CelesTrak TLE + SGP4)
- `worker-neo` (NASA NEO + JPL SBDB)
- `worker-space-weather` (NOAA SWPC)
- `worker-weather` (NOAA GFS, Open-Meteo)
- `worker-news-rss` (Reuters / AP / BBC / ISW / Bellingcat)
- `worker-mesh` (Meshtastic / APRS / KiwiSDR)

Note: USGS Quake, GDACS, NASA FIRMS were Layer 3 in an earlier draft. They are **promoted to Module C** (composite input) by the multi-modal re-anchor.

Adding a Layer 3 worker = new file in `app/workers/`, new queue entry in `celery_app.py`, no schema change.

---

## Boundary rules

These are invariants. The system stays sane only if they hold.

1. **Workers only write** to `events` table and to Parquet archive. They never query other workers' outputs directly.
2. **API only reads** from `events` and `scores`. The read API is stateless and side-effect-free.
3. **Composite worker is the only writer of `scores`.** It reads `events`, computes scores, writes back.
4. **No worker calls another worker.** All cross-module signal flow happens via the database (events written by A and B are read by D).
5. **All ingestion is idempotent.** Re-running the same fetch produces no duplicate rows. Dedup key is documented per source in [`03-ingestion.md`](03-ingestion.md).

---

## Feed taxonomy

Critical split: **not every feed feeds the composite stress index.** The thesis defends a multi-modal composite over three input domains (geopolitical / market / hazard) with documented methodology; the rest of the feeds are dashboard, situational awareness, and personal use. Mixing them would explode the methodology and make the evaluation indefensible.

### Tier 1 — Thesis core (multi-modal composite inputs + ground truth)

| Feed | Module / role | Purpose | Free? |
|---|---|---|---|
| [Yahoo Finance (via `yfinance`)](https://github.com/ranaroussi/yfinance) | A — Market | Equities, indices, FX, crypto, vol | Yes |
| [FRED](https://fred.stlouisfed.org/docs/api/fred/) | A — Market | CPI, unemployment, GDP, yield curves | Yes |
| FinBERT on financial RSS news ([model card](https://huggingface.co/ProsusAI/finbert)) | A — Market (auxiliary) | News-tone signal, used as auxiliary not anchor | Yes |
| [GDELT v2 events + GKG](https://www.gdeltproject.org/data.html#rawdatafiles) | B — Geopolitical | Deduplicated, CAMEO-filtered, Goldstein per country | Yes |
| [USGS Earthquake feed](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) | C — Hazard | Seismic events with magnitude + fatality proxy | Yes |
| [GDACS multi-hazard alerts](https://www.gdacs.org/) | C — Hazard | Cyclone / flood / volcano / drought alert levels | Yes |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | C — Hazard | Fire hotspots, satellite-detected | Yes |
| [ACLED](https://acleddata.com/) | Ground truth — geopolitical | Conflict events (P1-P3 labels) | Yes (academic registration) |
| NBER + IMF currency-crisis + FRED VIX | Ground truth — market | Market crisis labels (P4) | Yes |
| [EM-DAT](https://www.emdat.be/) + GDACS red-alerts | Ground truth — hazard | Hazard-induced disruption labels (P5) | Yes (academic registration) |

Three input domains (A + B + C), three label domains. The composite is evaluated against an any-positive multi-modal target per [`../evaluation-protocol.md`](../evaluation-protocol.md). Per the JRC composite indicator handbook ([source](https://composite-indicators.jrc.ec.europa.eu/?q=content/10-step-guide)), defensible weights on a small, justified domain set beats kitchen-sink aggregation.

### Tier 2 — Layer 3 dashboard (display, alerts, NOT in composite)

**Tracking**
- [OpenSky Network](https://opensky-network.org/) — ADS-B aircraft (60 s, key required)
- [adsb.lol](https://www.adsb.lol/) — military mode-S (no key)
- [AISStream.io](https://aisstream.io/) — AIS vessels (WebSocket, free key)

**Wars / geopolitics**
- ISW RSS, Bellingcat, Reuters / AP / BBC / AFP / Al Jazeera RSS bundle
- [DeepState Map](https://deepstatemap.live/) — Ukraine front (~30 min)
- ACLED live — conflict events on map (separate from ACLED-as-ground-truth use)

**Weather / space weather**
- [NOAA GFS](https://www.nco.ncep.noaa.gov/pmb/products/gfs/) — forecast GRIB
- [Open-Meteo](https://open-meteo.com/) — historical + forecast weather, no key
- [NOAA SWPC](https://www.swpc.noaa.gov/products) — solar storms, Kp index

(USGS Quake, GDACS, NASA FIRMS are now Tier 1 / Module C — see table above.)

**Space / satellites**
- [CelesTrak](https://celestrak.org/) — TLEs for every orbital object; SGP4 propagator runs locally
- [NASA NEO](https://api.nasa.gov/) — near-Earth asteroids
- [JPL Small-Body DB](https://ssd.jpl.nasa.gov/) — asteroid orbits
- [N2YO](https://www.n2yo.com/api/) — satellite passes per location

**Markets / economics**
- `yfinance` — equities, indices, FX, crypto
- [FRED](https://fred.stlouisfed.org/) — CPI, unemployment, GDP, yields
- [ECB SDW](https://sdw.ecb.europa.eu/) — EU rates
- [World Bank Open Data](https://data.worldbank.org/) — GDP, debt
- [Alpha Vantage](https://www.alphavantage.co/) + [Finnhub](https://finnhub.io/) free tiers — fundamentals

**Off-grid bonus** (Shadowbroker DNA)
- [APRS-IS](https://www.aprs-is.net/) — amateur radio positions
- [KiwiSDR](http://kiwisdr.com/public/) — public SDR list
- Own [Meshtastic](https://meshtastic.org/) node — mesh radio reachable via Pi

### Tier 3 — Out of scope

Explicitly not building (be honest with examiners):

- Palantir-style entity resolution / ontology across feeds
- Commercial satellite imagery (Maxar, Planet — $$$)
- Private intelligence feeds
- Telegram OSINT scraping at Shadowbroker's depth (TOS + legal risk)

---

## What this system is NOT

- It is not Palantir Foundry. No ontology, no analyst workflows, no enterprise auth.
- It is not Shadowbroker. No mesh layer, no agentic AI channel, no decentralised governance. (Those can be added in Layer 3 if Basil wants, but they are not architectural commitments.)
- It is not a prediction system. The composite reports stress level; it does not claim to forecast specific events. The evaluation in [`../evaluation-protocol.md`](../evaluation-protocol.md) tests **discrimination** (does high stress correlate with later labelled instability events across the three domains) rather than **prediction accuracy** in the strict sense.
- It is not finance-anchored. An earlier draft framed the thesis as a finance-led composite. The current re-anchor treats market signals as one of three equal input domains in the multi-modal composite; finance is not the headline contribution.
