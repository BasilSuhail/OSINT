# 04 — Common Event Schema

Marco's brief requires a common event table with fields: **time, location, source, category, severity, keywords, confidence**. This file is the canonical definition, plus the supporting tables that make the rest of the system work.

- [`events` table](#events-table)
- [`scores` table](#scores-table)
- [Ground-truth label tables](#ground-truth-label-tables)
- [Supporting tables](#supporting-tables)
- [Indexes](#indexes)
- [Migrations](#migrations)
- [Cross-source category vocabulary](#cross-source-category-vocabulary)

---

## `events` table

The canonical input for every fetcher across all three composite domains plus Layer 3.

```sql
CREATE TABLE events (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,           -- 'gdelt', 'yfinance', 'fred', 'usgs-quake', 'gdacs', 'nasa-firms', ...
    source_event_id TEXT NOT NULL,           -- source-specific stable id
    occurred_at     TIMESTAMPTZ NOT NULL,    -- event time (NOT fetch time)
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    category        TEXT NOT NULL,           -- see vocabulary below
    severity        REAL,                    -- 0..1, source-normalised; NULL if N/A
    confidence      REAL,                    -- 0..1; NULL if source does not provide
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    country         CHAR(2),                 -- ISO 3166-1 alpha-2, NULL if global/none
    lat             DOUBLE PRECISION,        -- decimal degrees, NULL if N/A
    lon             DOUBLE PRECISION,
    payload         JSONB NOT NULL,          -- full source record
    CONSTRAINT events_severity_range   CHECK (severity   IS NULL OR severity   BETWEEN 0 AND 1),
    CONSTRAINT events_confidence_range CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

CREATE UNIQUE INDEX events_source_id_idx ON events (source, source_event_id);
```

Field rules:

- `occurred_at` is **event time**, never fetch time. GDELT event date, AIS message timestamp, market tick time, USGS quake origin time. This is what makes retrospective evaluation honest.
- `severity` is **source-normalised to 0..1** by the fetcher. Documented per fetcher:
  - GDELT Goldstein (–10..+10) → `1 - (goldstein + 10) / 20` so escalatory events are higher
  - USGS magnitude → `min(1, max(0, (mag - 3) / 7))`
  - Market drawdown → `min(1, drawdown_pct / 30)`
  - GDACS alert level → `{Green: 0.2, Orange: 0.6, Red: 1.0}`
- `payload` keeps the full record so the composite worker can change its input feature engineering without re-ingestion.
- `country` is the **primary country** the event is about. Multi-country events (a cross-border attack, a global market move) get a row per country, all sharing the same `source_event_id` — exception to the dedup rule, documented per fetcher.

---

## `scores` table

Output of the composite worker and of every baseline. Country-month resolution by default, but the schema allows daily for higher-resolution sources.

```sql
CREATE TABLE scores (
    id              BIGSERIAL PRIMARY KEY,
    country         CHAR(2) NOT NULL,
    bucket_start    TIMESTAMPTZ NOT NULL,    -- start of the time bucket
    bucket_length   INTERVAL NOT NULL,       -- '1 day' | '1 month'
    score_name      TEXT NOT NULL,           -- 'composite' | 'market-only' | 'geo-only' | 'hazard-only' | 'B1-persistence' | ...
    score_value     REAL NOT NULL,           -- 0..1 normalised
    components      JSONB NOT NULL,          -- {"market": 0.42, "geo": 0.18, "hazard": 0.05} or similar per-baseline breakdown
    method_version  TEXT NOT NULL,           -- 'v1.0', 'v1.1', ...
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scores_value_range CHECK (score_value BETWEEN 0 AND 1)
);

CREATE UNIQUE INDEX scores_unique_idx ON scores (country, bucket_start, bucket_length, score_name, method_version);
```

`method_version` is the lock against silently changing the methodology mid-evaluation. The evaluation protocol locks v1.0 with Marco before Week 4; later versions can coexist for ablations.

The same table holds every baseline (B0 random, B1 persistence, B2 base rate, B3 geo-only, B4 market-only, B5 hazard-only, B6/B7/B8 composite variants) — each is just another `score_name`. The evaluation join is then a single query keyed on `(country, bucket_start, bucket_length, method_version)`.

---

## Ground-truth label tables

Kept **separate from `events`** because labels are not OSINT observations — they are the answer key. Mixing them with the input data is a category error and risks accidental look-ahead leakage.

```sql
CREATE TABLE labels (
    id              BIGSERIAL PRIMARY KEY,
    country         CHAR(2) NOT NULL,
    bucket_start    TIMESTAMPTZ NOT NULL,
    bucket_length   INTERVAL NOT NULL,
    label_code      TEXT NOT NULL,           -- 'P1' | 'P2' | 'P3' | 'P4' | 'P5'
    label_source    TEXT NOT NULL,           -- 'acled' | 'nber' | 'imf-currency' | 'fred-vix' | 'em-dat' | 'gdacs-red'
    source_record_id TEXT,                   -- ACLED event_id_cnty, NBER cycle id, ...
    magnitude        REAL,                   -- fatality count, drawdown pct, affected population, etc.
    payload          JSONB NOT NULL,         -- full label source record
    locked_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX labels_unique_idx ON labels (country, bucket_start, bucket_length, label_code, label_source, COALESCE(source_record_id, ''));
CREATE INDEX labels_country_bucket_idx ON labels (country, bucket_start);
```

Label codes match [`../methodology.md`](../methodology.md#step-2--ground-truth-hybrid-multi-modal):

| Code | Domain | Sources |
|---|---|---|
| `P1` | Geopolitical — armed conflict onset | ACLED |
| `P2` | Geopolitical — mass protest escalation | ACLED |
| `P3` | Geopolitical — state-based violence intensification | ACLED |
| `P4` | Market — country-level market crisis | NBER, IMF currency-crisis, FRED VIX, sovereign yield, equity drawdown |
| `P5` | Hazard — hazard-induced societal disruption | EM-DAT, GDACS red-alerts (with composite-stress filter) |

Eval queries join `scores` to `labels` on `(country, bucket_start, bucket_length)` and check whether any positive label falls in the future horizon window `[t+1, t+k]`.

---

## Supporting tables

```sql
-- Per-fetcher health, one row per source per UTC day
CREATE TABLE ingest_health (
    source       TEXT NOT NULL,
    day          DATE NOT NULL,
    success_n    INTEGER NOT NULL DEFAULT 0,
    failure_n    INTEGER NOT NULL DEFAULT 0,
    last_success TIMESTAMPTZ,
    last_failure TIMESTAMPTZ,
    PRIMARY KEY (source, day)
);

-- Ingest failures, full trace for debugging
CREATE TABLE ingest_failures (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_class   TEXT NOT NULL,
    error_message TEXT,
    request_url   TEXT,
    response_body TEXT,
    payload       JSONB
);

-- Dead-letter for replay after a transient outage
CREATE TABLE dead_letter_queue (
    id            BIGSERIAL PRIMARY KEY,
    task_name     TEXT NOT NULL,
    fetcher_name  TEXT NOT NULL,
    enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    replay_after  TIMESTAMPTZ NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT
);

-- Housekeeping run audit (hot/cold mover, retention, etc.)
CREATE TABLE housekeeping_runs (
    id             BIGSERIAL PRIMARY KEY,
    ran_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    job_name       TEXT NOT NULL,           -- 'hot-to-cold-mover' | 'restic-backup' | 'btrfs-scrub' | ...
    archived_count INTEGER NOT NULL DEFAULT 0,
    deleted_count  INTEGER NOT NULL DEFAULT 0,
    duration_ms    INTEGER NOT NULL,
    notes          TEXT
);

-- Sent notifications, for de-duping alert spam
CREATE TABLE notifications (
    id          BIGSERIAL PRIMARY KEY,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel     TEXT NOT NULL,             -- 'pushover'
    country     CHAR(2),
    score_value REAL,
    message     TEXT NOT NULL,
    dedup_key   TEXT NOT NULL UNIQUE
);
```

---

## Indexes

```sql
CREATE INDEX events_occurred_at_idx        ON events (occurred_at DESC);
CREATE INDEX events_country_occurred_idx   ON events (country, occurred_at DESC);
CREATE INDEX events_category_idx           ON events (category, occurred_at DESC);
CREATE INDEX events_source_occurred_idx    ON events (source, occurred_at DESC);

-- Composite worker reads recent events by country
CREATE INDEX events_country_recent_idx
    ON events (country, occurred_at DESC)
    WHERE occurred_at > now() - interval '90 days';
```

The partial index is the one that keeps composite-worker queries fast as `events` grows. The 90-day window matches the hot/cold split in [`02-storage.md`](02-storage.md#hot--cold-split).

---

## Migrations

- Tool: [Alembic](https://alembic.sqlalchemy.org/) (plays nicely with SQLAlchemy models)
- Layout: `migrations/versions/<timestamp>_<slug>.py`
- Rule: schema changes are PR'd, never applied in-place on the Pi without the migration committed first
- Backup: every `alembic upgrade head` runs after a `pg_dump` to `/mnt/data/backups/pg/pre-<revision>.sql`
- Down-migrations: optional, only for changes that can be reversed without data loss; otherwise document the manual recovery path in the migration body

---

## Cross-source category vocabulary

The `category` field is constrained to a fixed vocabulary so the dashboard's category filter is meaningful. Categories track the **input domain**, not the label domain:

| Category | Used by sources | Composite role |
|---|---|---|
| `market` | yfinance, FRED, ECB, World Bank, Alpha Vantage, Finnhub, FinBERT-on-RSS | Module A — composite input |
| `geopolitical` | GDELT events, GDELT GKG | Module B — composite input |
| `hazard` | USGS Quake, GDACS, NASA FIRMS | Module C — composite input |
| `weather` | NOAA GFS, Open-Meteo, NOAA SWPC | Layer 3 dashboard only |
| `tracking` | OpenSky, adsb.lol, AISStream | Layer 3 dashboard only |
| `space` | CelesTrak, NASA NEO, JPL SBDB, N2YO | Layer 3 dashboard only |
| `news` | Reuters / AP / BBC / ISW / Bellingcat / Al Jazeera RSS | Layer 3 dashboard only |
| `cyber` | abuse.ch, CISA KEV (Layer 3) | Layer 3 dashboard only |
| `mesh` | Meshtastic, APRS, KiwiSDR | Layer 3 dashboard only |

Adding a category = PR that updates this list **and** the dashboard's category filter component. The category enum is enforced at the application layer (Pydantic), not in Postgres, so changes do not require a migration.

The composite worker selects only rows where `category IN ('market', 'geopolitical', 'hazard')`. Everything else is dashboard breadth and never enters the composite computation — this is the architectural barrier that keeps the JRC methodology defensible.

### Note on FIRMS routing

NASA FIRMS active-fire detections are routed to **`hazard`**, not `weather`, even though the upstream sensor (VIIRS) is meteorological. This is intentional:

- The OECD / JRC composite-indicator handbook clusters hazards (geophysical + climatological + wildfire) into one domain — splitting them across `weather` and `hazard` would invalidate the three-domain composite definition the thesis uses.
- A fire detection is a stress event in its own right (loss of life, displacement, economic damage), not a weather forecast.
- Keeping the three-domain composite stable (market / geopolitical / hazard) means adding a fourth `weather` domain is a methodology change, not a casual schema tweak — to be considered for a v2.0 composite if the thesis benefits from it.

The same rationale applies to NASA EONET wildfires / floods / volcanoes (`hazard`). Storm trajectories and `severeStorms` events are also routed to `hazard` for now; if the eval signal suggests a separate weather domain helps, we revisit.
