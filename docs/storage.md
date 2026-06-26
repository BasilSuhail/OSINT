# Storage & data — where everything lives, and how to manage it

Practical guide to the local, off-grid storage model (no Supabase, no cloud).
For the original design rationale see [`architecture/02-storage.md`](architecture/02-storage.md);
this doc is the **operational** reference.

---

## TL;DR

- **One variable** decides where data lives: `OSINT_DATA_DIR` (default `./data`).
- **Live database** = `data/postgres/` + `data/redis/`. The app reads/writes this constantly.
- **Backups** = `backups/<timestamp>/` — frozen CSV copies made on demand by `snapshot.py`.
- **Retention** auto-trims the live DB to the last few days so it stays small.

---

## The three things people confuse

These are genuinely different. Mixing them up is the usual source of "where's my data?".

| | What it is | Lives where | App uses it? | If you delete it |
|---|---|---|---|---|
| **`OSINT_DATA_DIR`** | A **config variable** (a pointer/address). Just a string. | `.env` (or the `./data` default) | indirectly — tells everything *where* the data folder is | nothing breaks; re-point and restart |
| **Physical data** | The **live database files** — the actual rows | `data/postgres/`, `data/redis/` | ✅ constantly (read + write) | you lose current state (restore from a backup) |
| **Backups** | **Frozen point-in-time copies** (gzipped CSV per table) | `backups/<utc-timestamp>/` | ❌ never — passive archive | you lose your safety net (live DB unaffected) |

**Analogy:** `OSINT_DATA_DIR` is the **address**, `data/` is the **house with your stuff**, `backups/` is a **set of photos of the house** stored somewhere safe.

---

## `OSINT_DATA_DIR` — the pointer

A single env var that sets the root folder for **all** local storage. Default `./data` (inside the repo, gitignored).

**Wired in three places** (all read the same var, default to `./data`):

| Place | File | Purpose |
|---|---|---|
| App default | `app/settings.py` → `data_dir` field | Python code reads it |
| Containers | `docker-compose.yml` → `${OSINT_DATA_DIR:-./data}/postgres` and `/redis` | bind-mounts the data into Postgres/Redis |
| Tooling | `Makefile` (reads it from `.env`, else `./data`) | `make data-size` / `data-prune` / `data-reset` |

**Not set in `.env` → uses the default `./data`.** To check the current value:

```bash
grep '^OSINT_DATA_DIR=' .env || echo "(unset → ./data)"
```

### Moving it (e.g. Raspberry Pi + external HDD)

Add one line to `.env`, then recreate the containers:

```bash
echo 'OSINT_DATA_DIR=/mnt/hdd/osint' >> .env
docker compose down          # stops containers (data is just files on disk)
docker compose up -d         # Postgres/Redis now read/write the new path
```

The repo stays small; the database lives on the chosen disk. Nothing else changes.

> First run against an **empty** new path needs the schema created:
> `.venv/bin/alembic upgrade head`.

---

## Physical data — the live database

```
$OSINT_DATA_DIR/                 (default ./data, gitignored)
├── postgres/      ← Postgres 16 data directory — the real DB (events, scores, …)
└── redis/         ← Redis append-only file — Celery broker/result state + the live-event pub/sub
```

- This is what the running stack reads and writes every second.
- It is **bind-mounted** into the Docker containers, so the data outlives any
  container — stop/recreate the containers freely; the files persist.
- `data/redis/` only appears once the Redis container is (re)created under the
  bind-mount; `data/postgres/` is created on first `docker compose up`.

Check size:

```bash
make data-size            # du -sh of each subfolder
```

### Why it stays small — retention

The pipeline keeps only the **latest few days** (the dashboard never shows more).
Defined in `app/housekeeping.py`, run daily at **03:00 UTC** by Celery beat:

| Data | Kept | Override (`.env`) |
|---|---|---|
| GDELT (largest) | 2 days | `RETENTION_GDELT_DAYS` |
| News (RSS) | 3 days | `RETENTION_NEWS_DAYS` |
| Hazard / cyber / aviation / markets-live | 2 days | `RETENTION_HAZARD_DAYS` |
| UK police | 7 days | — |
| yfinance | 30 days | — |
| FRED macro | forever (irreplaceable) | — |

Force a prune now (don't wait for 03:00):

```bash
make data-prune           # runs scripts/prune_now.py
```

> Lesson from the Supabase era: retention was never actually running there, so
> the DB grew to ~1.49 M events / 911 MB. Locally the 03:00 prune keeps it tiny.

---

## Backups — frozen copies

`scripts/snapshot.py` streams each table to a gzipped CSV — a "roll back to when
it worked" archive. The live DB is untouched; these are passive files.

```bash
.venv/bin/python -m scripts.snapshot                 # all tables
.venv/bin/python -m scripts.snapshot --skip events   # everything but the big one
```

Output:

```
backups/<UTC-timestamp>/
├── events.csv.gz
├── scores.csv.gz
├── … (one per table)
└── manifest.json     ← git sha + per-table row counts + source host
```

`backups/` is gitignored — never committed. Restore one table into a running DB:

```bash
gunzip -c backups/<ts>/scores.csv.gz | \
  docker compose exec -T postgres psql -U osint -d osint \
  -c "COPY scores FROM STDIN WITH CSV HEADER"
```

---

## Common operations

| Goal | Command |
|---|---|
| See disk used | `make data-size` |
| Trim old rows now | `make data-prune` |
| Back up before risky changes | `.venv/bin/python -m scripts.snapshot` |
| **Wipe everything and start clean** | `make data-reset` *(stops stack + `rm -rf $OSINT_DATA_DIR`)* |
| Rebuild empty schema after a wipe | `docker compose up -d && .venv/bin/alembic upgrade head` |
| Move data to another disk | set `OSINT_DATA_DIR` in `.env`, then `docker compose down && up -d` |

> `make data-reset` is destructive — it deletes the live DB. Take a
> `snapshot.py` backup first if the data matters.

---

## Safety notes

- `.env` holds secrets (DB password, API keys) — gitignored, **never commit it**.
- `data/` and `backups/` are gitignored — they never enter the repo.
- A backup is only as safe as the disk it sits on; for the Pi, keep `backups/`
  (or copies) on a separate drive from `OSINT_DATA_DIR`.
- Deleting the **cloud** Supabase project is unrelated to local storage — local
  data lives entirely in `OSINT_DATA_DIR` and survives regardless.

See also: [run book in the README](../README.md#run-book--turn-it-on--off) ·
[project map](../README.md#project-map--where-everything-lives).
