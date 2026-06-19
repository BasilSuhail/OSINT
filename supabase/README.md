# Supabase setup

Using a managed Supabase project instead of the local docker Postgres. Faster to start, no docker friction, built-in table editor for browsing data, and a clean migration path to a self-hosted Pi DB later via `pg_dump` / `pg_restore`.

## Step 1 — Create the project

1. Sign in at [supabase.com](https://supabase.com).
2. **New Project** → give it a name like `osint-dev`.
3. Pick a strong **database password** (you will paste this into `.env`).
4. Pick a region close to you (Europe West for UK).
5. Wait ~2 minutes for the project to provision.

The free tier ships with 500 MB of database storage. That is plenty for the first months of ingestion; the historical backfill PR will document how to monitor and prune.

## Step 2 — Get the connection string

1. Project sidebar → **Project Settings** → **Database**.
2. Scroll to **Connection string** → tab **URI**.
3. Copy the line, it looks like:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxx.supabase.co:5432/postgres
   ```
4. Replace `[YOUR-PASSWORD]` with the database password you picked in Step 1.

## Step 3 — Update `.env`

Open `.env` and set:

```bash
POSTGRES_HOST=db.xxxxxxxx.supabase.co
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-supabase-database-password
```

Leave everything else as-is. The codebase only reads these five variables; it does not care whether the Postgres is local docker or Supabase or a Pi.

## Step 4 — Apply the schema

You have two options. Pick one.

### Option A — Paste the SQL file (easiest)

1. Supabase sidebar → **SQL Editor** → **New query**.
2. Open [`01_schema.sql`](01_schema.sql) and copy the whole file.
3. Paste into the query window.
4. Click **Run**.
5. Verify all 8 tables appear under **Database** → **Tables**:
   - `events`, `scores`, `labels`, `ingest_health`, `ingest_failures`, `dead_letter_queue`, `housekeeping_runs`, `notifications`.

The SQL is idempotent — re-running is safe.

### Option B — Run Alembic from your laptop

```bash
source .venv/bin/activate
alembic upgrade head
```

Same result. Use this if you want the Alembic version table managed for you (the SQL file inserts `'0001'` into `alembic_version` so future migrations work either way).

## Step 5 — Stop the local docker Postgres

If you previously had `docker compose up -d` running:

```bash
docker compose stop postgres
# Or comment out the postgres service in docker-compose.yml entirely.
```

Keep the `redis` service running — Celery still needs it locally until you move queue infra somewhere else.

## Step 6 — Smoke test

```bash
source .venv/bin/activate
python -c "
from app.fetcher_registry import get_fetcher
from app.db import session_scope
from app.persistence import upsert_events
events = get_fetcher('yfinance').fetch()
print(f'fetched {len(events)}')
with session_scope() as s:
    n = upsert_events(events, s)
print(f'upserted {n}')
"
```

Then open Supabase → **Table Editor** → `events`. Real rows should be there.

## Migration to a self-hosted Pi later

When the Pi is online with btrfs RAID1:

```bash
# On laptop, dump the Supabase database
pg_dump "postgresql://postgres:PASSWORD@db.xxxxxxxx.supabase.co:5432/postgres" \
    --no-owner --no-privileges \
    > osint_backup.sql

# On Pi, after `docker compose up -d` brings up a fresh Postgres
psql "postgresql://osint:PASSWORD@localhost:5432/osint" < osint_backup.sql
```

Then update `.env` on the Pi to point at the local Postgres and decommission the Supabase project.

## Quotas

| Limit | Free tier | Likely impact |
|---|---|---|
| Database size | 500 MB | ~2-3 months of live ingestion at current cadence. Historical backfill may push past this. |
| Project pauses after 1 week inactive | Yes | Composite worker runs hourly; never inactive. |
| Concurrent connections | 60 | Celery uses ~2. Comfortable. |
| Egress | 5 GB/month | Tiny — pulling rows for the composite is cheap. |

If quotas tighten, the migration path to Pi (above) is one `pg_dump`.
