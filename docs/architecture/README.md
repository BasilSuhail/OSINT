# Architecture Spec

Companion to the top-level [`../../README.md`](../../README.md) (project plan), [`../methodology.md`](../methodology.md) (evaluation protocol + literature baseline).

This directory specifies **how the system is built**. Each section is a standalone file so it can be reviewed, linked, and updated independently. Start at section 01 and read in order; each section assumes the previous ones.

**Status**: spec is fully drafted (sections 01-07). Next phase is code implementation, scoped separately.

## Sections

| # | File | What it covers | Status |
|---|---|---|---|
| 01 | [`01-overview.md`](01-overview.md) | High-level architecture, module map, feed taxonomy (project core vs Layer 3) | Draft |
| 02 | [`02-storage.md`](02-storage.md) | btrfs RAID1 layout, hot/cold split, snapshots, off-site backup | Draft |
| 03 | [`03-ingestion.md`](03-ingestion.md) | Celery queue tiers, fetcher contract, dedup, retry, rate limiting | Draft |
| 04 | [`04-schema.md`](04-schema.md) | `events`, `scores`, `labels`, supporting tables, indexes, category vocabulary | Draft |
| 05 | [`05-originality.md`](05-originality.md) | Independence, what the architecture shares with every system, where the substance is, claims and disclaimers, provenance trail | Draft |
| 06 | [`06-validation.md`](06-validation.md) | Methodological hooks for `methodology.md`, runtime health + plausibility + snapshot tests, replayability, pre-evaluation checklist | Draft |
| 07 | [`07-risks.md`](07-risks.md) | Risk register: hardware, data, methodology, schedule, operations, legal/policy. Includes load-bearing Week-7 Layer 3 hard-stop and Tier-1-only project-report scope rule | Draft |

## Quick context

- **Scope**: Hybrid — project-grade depth (Modules A, B, D + ACLED ground truth) plus personal Layer 3 breadth (flights, ships, satellites, weather, etc.)
- **Hardware**: Raspberry Pi 5 (8 GB) + 2x4TB USB3 HDDs in btrfs RAID1
- **Stack**: FastAPI (read API), Celery + Redis (workers + queue), Postgres 16 (hot store), Parquet on btrfs (cold archive), Next.js + MapLibre GL (frontend, built off-Pi)
- **Independence**: built from nothing, no external source code used; see [`05-originality.md`](05-originality.md)

## Working agreement

This spec is the source of truth for the build. Anything beyond what is written here is out of scope until added to this spec by a separate PR.
