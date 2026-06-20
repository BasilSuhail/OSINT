# Hybrid Architecture Spec — Pi 5 + btrfs RAID1 + Celery Pipeline

**Scope.** This document is the load-bearing reference for the hybrid build: thesis-grade Modules A–E on top of personal Layer-3 breadth, deployed on commodity hardware. It locks the decisions taken across the existing `docs/architecture/01..07` series and adds the Pi-specific deployment plan.

For deep dives by topic, consult:

- [01 — Overview](architecture/01-overview.md)
- [02 — Storage](architecture/02-storage.md)
- [03 — Ingestion](architecture/03-ingestion.md)
- [04 — Common Event Schema](architecture/04-schema.md)
- [05 — Originality defence](architecture/05-originality.md)
- [06 — Validation hooks](architecture/06-validation.md)
- [07 — Risks + mitigations](architecture/07-risks.md)

This file is the **single-page** spec referenced from `docs/master-plan.md` and from the dissertation. It does not duplicate the deep dives; it locks the decisions and tabulates the deployment plan.

---

## 1. Architecture choice — locked

**Option B: Pipeline + worker.** FastAPI read-only API, Celery workers behind a Redis queue, Postgres hot store, Parquet cold archive, Next.js dashboard built off-host and served as static assets.

Why not A (monolith): Module-D composite worker needs to run on a different cadence than HTTP requests; pinning everything in the request loop would either starve the API or starve the worker.

Why not C (microservices): unnecessary operational tax for a single-author thesis. Two queues (`fast` / `slow`) inside one Celery app is the right midpoint.

Module map:

| Module | Responsibility | Code path |
|---|---|---|
| A | Market signals | `app/sources/{yfinance,fred}_fetcher.py` |
| B | Geopolitical events | `app/sources/{gdelt,gdelt_parser}.py` |
| C | Hazards | `app/sources/{usgs_quake,gdacs,nasa_firms,eonet}_fetcher.py` |
| D | Composite worker | `app/composite/{aggregation,normalization,scoring,task}.py` |
| E | Evaluation (pending) | `app/evaluation/*` — created when #65 closes |
| L3 | Dashboard / Layer-3 breadth | `osint-frontend/` |

---

## 2. Hardware — locked

- **Compute.** Raspberry Pi 5 8 GB RAM, active cooler. PoE+ HAT for power resilience.
- **Storage.** 2 × 4 TB SATA SSD in UAS-compatible USB 3.2 enclosures. **btrfs RAID1** across both devices.
- **Network.** Wired Gigabit Ethernet only. Wifi disabled at the OS layer to avoid silent failover during eval windows.
- **Frontend host.** Vercel (free tier) — the dashboard is static-export-friendly and Vercel handles HTTPS + edge cache. Pi serves the FastAPI read API only.

Rationale on btrfs vs ZFS: btrfs RAID1 is in-tree on Linux 6.x and survives the disk being yanked + replugged into a fresh enclosure during demo — critical for an in-person viva. ZFS on Raspbian needs DKMS and is fragile under kernel upgrades.

---

## 3. Storage layout

See [`02-storage.md`](architecture/02-storage.md) for the long-form reasoning. Summary of the on-disk layout:

```
/mnt/raid1/                  # btrfs RAID1 mount, label "osint"
  postgres/                  # hot store: 90 d window of events + scores
  parquet/                   # cold archive partitioned by source/year/month
    yfinance/year=2026/...
    nasa-firms/year=2026/...
    ...
  backups/                   # nightly pg_dump + restic snapshots
  redis/                     # AOF (cold; the live Redis runs from tmpfs)
```

**Hot/cold split.** Postgres keeps the last 90 days of `events` (FIRMS is pruned at 30 d — see [`#76`](https://github.com/BasilSuhail/OSINT/issues/76) and `app/housekeeping.py`). Older data is exported to Parquet on the same volume; the composite worker can read both via `pyarrow` when an ablation needs longer history.

**Backup.** `restic` to a USB-attached encrypted backup drive nightly, with a quarterly off-site rsync to a second physical location. `btrfs scrub` runs monthly via systemd timer to catch silent corruption.

---

## 4. Ingestion pattern

See [`03-ingestion.md`](architecture/03-ingestion.md) for the per-source contract. Summary:

- **Two Celery queues.** `fast` for cheap fetchers (yfinance 5-min); `slow` for everything else.
- **Dedup.** `(source, source_event_id)` UNIQUE index. The upsert path is batched at 1000 rows/statement to stay under Postgres' 65 535-parameter cap (#57 / `app/persistence.py`).
- **Country enrichment.** `app/enrichment/country.py` resolves lat/lon → ISO 3166-1 alpha-2 inside the fetcher via Natural Earth polygons + STRtree (#66).
- **Retry.** Per-task exponential backoff at the Celery layer; per-source dead-letter queue (`dead_letter_queue` table) for transient outages.
- **Rate limit.** Beat schedule is the rate limit — fetchers do not have their own client-side throttling because every upstream we use is rate-limit-tolerant at our cadence (15-min or coarser).
- **Health.** `ingest_health` row per (source, day). Watchdog beat task pages via Pushover if any source goes stale by `cadence × 6` minutes (#71 / `app/watchdog.py`).
- **Retention.** `app/housekeeping.py` prunes per source policy (FIRMS 30 d, GDELT 90 d, USGS 365 d, FRED forever).

---

## 5. Common event schema

Authoritative definition lives in [`04-schema.md`](architecture/04-schema.md). Single canonical `events` table:

```
events(id, source, source_event_id, occurred_at, fetched_at,
       category, severity, confidence, keywords, country, lat, lon, payload)
```

`category ∈ {market, geopolitical, hazard, weather, tracking, space, news, cyber, mesh}`. The composite worker consumes only `{market, geopolitical, hazard}`. FIRMS is routed to `hazard` (rationale in `04-schema.md#note-on-firms-routing`).

`scores` table holds the composite + every baseline. `labels` table is intentionally separate — ground-truth answer key, not OSINT input.

---

## 6. Originality defence

Three-layer test from [`05-originality.md`](architecture/05-originality.md):

1. **Literal.** No copied code blocks > 5 lines from any prior project. Fetchers re-implement parsing from each upstream's official docs.
2. **Concept.** The composite-indicator methodology is OECD/JRC public; our novelty is the three-domain composite over heterogeneous OSINT feeds with the eval protocol below, not the math.
3. **Shallow wrapper.** Each fetcher does meaningful normalisation (per-source severity, country enrichment, dedup keys) — none are passthrough cURLs.

This file is referenced verbatim from the dissertation chapter on methodology contributions.

---

## 7. Validation hooks

[`06-validation.md`](architecture/06-validation.md) defines the evaluation protocol. Quick reference:

- **Labels.** ACLED for geopolitical (P1–P3), NBER + IMF + FRED for market (P4), EM-DAT + GDACS-red for hazard (P5).
- **Window.** 30-day forward horizon. A positive label inside `[t+1, t+30]` counts as a hit.
- **Metrics.** AUROC + AUPR, per domain and overall. Random / persistence / base-rate baselines computed in `scores` under separate `score_name` values for ablation.
- **Locking.** `method_version` in `scores` so a methodology tweak does not silently overwrite prior eval runs.
- **Gating.** Module E (`app/evaluation/*`) is intentionally not started until [#65](https://github.com/BasilSuhail/OSINT/issues/65) closes — eval signal is meaningless if the pipeline is buggy or the data thin.

---

## 8. Risks + mitigations

Cross-link to [`07-risks.md`](architecture/07-risks.md). Headline items:

| Risk | Mitigation |
|---|---|
| Pi disk failure | btrfs RAID1 + nightly restic + quarterly off-site |
| Upstream API breakage during eval window | Watchdog (#71) + dead_letter_queue replay + multi-source redundancy in each composite domain |
| Cold-start composite (all 0.5) | Historical backfill (#75) |
| Supabase free tier fill | Retention policy (#76) + Pi as final home |
| Power outage during fetch | PoE+ HAT with brief carry-over; Celery beat will catch up on restart |
| Reviewer originality challenge | Three-layer test above + literal-copy detection in CI (future) |

---

## 9. Deployment runbook (Pi)

Not yet exercised; this is the plan, to be promoted to an `OPERATIONS.md` once the Pi is provisioned.

1. Raspberry Pi OS Lite (64-bit) on SD card; first boot configures wifi-off + SSH-only.
2. Attach the two USB SSDs. `mkfs.btrfs -d raid1 -m raid1 /dev/sda /dev/sdb`. Mount at `/mnt/raid1` via `/etc/fstab` with `compress=zstd:3,noatime,autodefrag`.
3. Install Docker via apt; clone the repo; `docker compose -f deploy/docker-compose.pi.yml up -d`.
4. Postgres data dir bind-mounted to `/mnt/raid1/postgres`. Redis tmpfs with AOF copy to `/mnt/raid1/redis` every hour.
5. Restic init against `/mnt/raid1/backups`. Cron the nightly `restic backup /mnt/raid1/postgres /mnt/raid1/parquet`.
6. Tailscale or WireGuard tunnel so the dashboard can hit the FastAPI read API without exposing it to the public Internet.
7. Frontend deploy: GitHub Actions builds the Next.js static export and pushes to Vercel. Vercel env points to the API tunnel.

Operational targets, kept honest:

- p50 read latency from frontend to FastAPI < 300 ms
- Ingest beat lag < 2 × cadence for every source over a rolling 7-day window
- Backup restore time < 1 hour from a cold disk

---

## 10. What this spec does *not* cover

- Per-source fetcher prose (see `03-ingestion.md` + each `app/sources/*.py` module docstring).
- The composite scoring maths (`app/composite/*.py` + `06-validation.md`).
- Frontend component-level layout (see `docs/frontend/README.md` + `osint-frontend/`).

If you find yourself wanting to add detail in one of those areas to this file, add it to the appropriate deep-dive and leave the link here.
