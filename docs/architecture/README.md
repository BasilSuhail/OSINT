# Architecture Spec

Companion to [`../master-plan.md`](../master-plan.md), [`../evaluation-protocol.md`](../evaluation-protocol.md), [`../literature-baseline.md`](../literature-baseline.md), and [`../px5928-requirements-and-status.md`](../px5928-requirements-and-status.md).

This directory specifies **how the system is built**. Each section is a standalone file so it can be reviewed, linked, and updated independently. Sections are added one at a time so each can be read on GitHub before the next is written.

## Sections

| # | File | What it covers | Status |
|---|---|---|---|
| 01 | [`01-overview.md`](01-overview.md) | High-level architecture, module map, feed taxonomy (thesis core vs Layer 3) | Draft |
| 02 | `02-storage.md` | btrfs RAID1 layout, hot/cold split, snapshots, off-site backup | Pending |
| 03 | `03-ingestion.md` | Celery queue tiers, fetcher contract, dedup, retry, rate limiting | Pending |
| 04 | `04-schema.md` | Common event schema, scores table, supporting tables, indexes | Pending |
| 05 | `05-originality.md` | Defense against "copied Shadowbroker" charge (three flavours) | Pending |
| 06 | `06-validation.md` | Methodological + runtime validation, replayability, pre-eval checklist | Pending |
| 07 | `07-risks.md` | Risk register: hardware / data / methodology / schedule / ops / legal | Pending |

## Quick context

- **Scope**: Hybrid — thesis-grade depth (Modules A, B, D + ACLED ground truth) plus personal Layer 3 breadth (flights, ships, satellites, weather, etc.)
- **Hardware**: Raspberry Pi 5 (8 GB) + 2x4TB USB3 HDDs in btrfs RAID1
- **Stack**: FastAPI (read API), Celery + Redis (workers + queue), Postgres 16 (hot store), Parquet on btrfs (cold archive), Next.js + MapLibre GL (frontend, built off-Pi)
- **Inspiration**: [Shadowbroker](https://github.com/BigBodyCobain/Shadowbroker) — architectural ideas only, no code copied; see `05-originality.md` (pending)

## Working agreement

This spec is the source of truth for the build. Anything beyond what is written here is out of scope until added to this spec by a separate PR.
