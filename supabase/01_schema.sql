-- OSINT schema for Supabase / managed Postgres.
-- Matches docs/architecture/04-schema.md and migrations/versions/0001_initial_schema.py.
--
-- How to use:
--   1. Supabase project → SQL Editor → New query
--   2. Paste this whole file
--   3. Run
--   4. Verify all 8 tables appear in Database → Tables sidebar
--
-- Idempotent: every CREATE uses IF NOT EXISTS so re-running the file is safe.

-- ---------------------------------------------------------------------------
-- events: canonical ingest row produced by every fetcher.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.events (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    category        TEXT NOT NULL,
    severity        REAL,
    confidence      REAL,
    keywords        TEXT[] NOT NULL DEFAULT '{}'::text[],
    country         CHAR(2),
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    payload         JSONB NOT NULL,
    CONSTRAINT events_severity_range
        CHECK (severity IS NULL OR (severity BETWEEN 0 AND 1)),
    CONSTRAINT events_confidence_range
        CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS events_source_id_idx
    ON public.events (source, source_event_id);
CREATE INDEX IF NOT EXISTS events_occurred_at_idx
    ON public.events (occurred_at);
CREATE INDEX IF NOT EXISTS events_country_occurred_idx
    ON public.events (country, occurred_at);
CREATE INDEX IF NOT EXISTS events_category_idx
    ON public.events (category, occurred_at);
CREATE INDEX IF NOT EXISTS events_source_occurred_idx
    ON public.events (source, occurred_at);

-- ---------------------------------------------------------------------------
-- scores: composite + baseline outputs. method_version locks the run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.scores (
    id              BIGSERIAL PRIMARY KEY,
    country         CHAR(2) NOT NULL,
    bucket_start    TIMESTAMPTZ NOT NULL,
    bucket_length   INTERVAL NOT NULL,
    score_name      TEXT NOT NULL,
    score_value     REAL NOT NULL,
    components      JSONB NOT NULL,
    method_version  TEXT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scores_value_range CHECK (score_value BETWEEN 0 AND 1),
    CONSTRAINT scores_unique_idx UNIQUE
        (country, bucket_start, bucket_length, score_name, method_version)
);

-- ---------------------------------------------------------------------------
-- labels: ground-truth (ACLED, NBER, IMF, EM-DAT) — kept separate from events
-- so the answer key is never treated as a feature.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.labels (
    id                BIGSERIAL PRIMARY KEY,
    country           CHAR(2) NOT NULL,
    bucket_start      TIMESTAMPTZ NOT NULL,
    bucket_length     INTERVAL NOT NULL,
    label_code        TEXT NOT NULL,
    label_source      TEXT NOT NULL,
    source_record_id  TEXT,
    magnitude         REAL,
    payload           JSONB NOT NULL,
    locked_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS labels_country_bucket_idx
    ON public.labels (country, bucket_start);

-- ---------------------------------------------------------------------------
-- ingest_health: per-fetcher per-day success/failure counters.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ingest_health (
    source        TEXT NOT NULL,
    day           DATE NOT NULL,
    success_n     INTEGER NOT NULL DEFAULT 0,
    failure_n     INTEGER NOT NULL DEFAULT 0,
    last_success  TIMESTAMPTZ,
    last_failure  TIMESTAMPTZ,
    PRIMARY KEY (source, day)
);

-- ---------------------------------------------------------------------------
-- ingest_failures: full trace per failed fetch for debugging.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ingest_failures (
    id             BIGSERIAL PRIMARY KEY,
    source         TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_class    TEXT NOT NULL,
    error_message  TEXT,
    request_url    TEXT,
    response_body  TEXT,
    payload        JSONB
);

-- ---------------------------------------------------------------------------
-- dead_letter_queue: tasks awaiting replay after transient outages.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.dead_letter_queue (
    id             BIGSERIAL PRIMARY KEY,
    task_name      TEXT NOT NULL,
    fetcher_name   TEXT NOT NULL,
    enqueued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    replay_after   TIMESTAMPTZ NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT
);

-- ---------------------------------------------------------------------------
-- housekeeping_runs: audit of hot/cold mover, retention, scrub jobs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.housekeeping_runs (
    id              BIGSERIAL PRIMARY KEY,
    ran_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    job_name        TEXT NOT NULL,
    archived_count  INTEGER NOT NULL DEFAULT 0,
    deleted_count   INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER NOT NULL,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- notifications: sent alert audit with dedup key.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notifications (
    id           BIGSERIAL PRIMARY KEY,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel      TEXT NOT NULL,
    country      CHAR(2),
    score_value  REAL,
    message      TEXT NOT NULL,
    dedup_key    TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- Mark this initial schema in alembic_version so a later `alembic upgrade head`
-- against the same DB does not try to re-create everything.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INSERT INTO public.alembic_version (version_num)
    VALUES ('0001')
    ON CONFLICT DO NOTHING;
