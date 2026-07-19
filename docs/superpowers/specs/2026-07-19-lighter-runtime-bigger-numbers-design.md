# Lighter runtime, bigger numbers

Date: 2026-07-19

## Problem

The dashboard header reads `7,500 Events · 121 Countries · 46 Sources`. None of those
numbers describe the data. They describe the browser.

`WorldStatusPanel` computes `stats.total` as `events.length` over the rows the client
happens to be holding, and that array is capped by `CLIENT_LIMITS.eventBuffer` (7500) in
`osint-frontend/lib/apiClient.ts`. The country and source counts are `distinct` over the
same truncated slice. The cap was lowered deliberately in #456 to stop local memory from
multiplying across Postgres, FastAPI, Next dev, browser state, and map state.

Measured against the live database on 2026-07-19:

| query (30-day window)                    | result                                  | time   |
| ---------------------------------------- | --------------------------------------- | ------ |
| count, excluding `opensky-adsb`          | 456,577 events / 179 countries / 52 srcs | 9.4 s  |
| count, all sources                       | 10,535,811 events                        | 80.5 s |

Database size: 7,221 MB against a 30 GB cap. `opensky-adsb` alone holds 10,072,097 rows —
96% of the table — at ~190k rows/day, and is never rendered.

So raising the client cap is the wrong lever: it trades browser RAM for a number that is
still smaller than the truth. The right lever is to stop counting in the browser at all,
and to stop storing a firehose we only consume as a rate.

## Goals

- Header shows true database counts, not buffer length.
- Browser RAM goes down, not up.
- Ingestion CPU and database disk go down.
- Map can represent every event without holding every event.

## Non-goals

- Adding new sources or raising fetch cadence. Ingestion volume is already ample.
- Raising `api_max_limit` or any client row cap.
- Retention policy changes. The 30-day / 30 GB rules from #354 stand.

## Work breakdown

Four independent pieces, one issue → branch → PR → commit each.

### PR 1 — Delete the globe

Remove the WebGL globe entirely; the 2D map becomes the only geographic view.

Deleted: `components/GlobePane.tsx`, `lib/satellites.ts`, `lib/neos.ts`,
`components/EphemerisChip.tsx`, `components/SatelliteDetailCard.tsx`, the
`/api/satellites` and `/api/neos` routes, the FilterRail "Live satellites" control, and
the `three`, `react-globe.gl`, `@types/three` dependencies. `SplitLayout` and
`rightPaneModeStore` lose the globe/map switch and render the map unconditionally.

Verification confirms nothing outside the globe imports these modules before deletion.

The globe-only FIRMS pull (`fetchFirmsEvents`, 1000 rows, `CLIENT_LIMITS.firmsEvents`) is
dropped only if `MapPane` proves not to consume it; otherwise it stays untouched.

Win: an entire WebGL context — geometry, textures, per-frame render loop, satellite and
asteroid state — leaves the tab. No backend risk.

### PR 2 — Aggregate opensky at ingest

`opensky_fetcher` stops emitting one event per aircraft observation. It emits per-country,
per-hour flight-density rows instead: `source="opensky-adsb"`, `category="flight-density"`,
observation count carried in `payload`, `occurred_at` at the hour boundary. Roughly 190k
rows/day becomes roughly 4k/day.

`app/divergence/config.py` is the only consumer and treats opensky as a sensor rate, not as
individual aircraft, so the aggregate preserves its input.

A migration collapses the existing 10,072,097 raw rows into hourly rollups and then deletes
the raw rows.

**Safety, in order:** dump the opensky slice to `backups/` with `pg_dump` first; write the
rollups; assert the rollup reproduces divergence's current inputs; only then delete raw.
The delete is one-way.

Win: database 7.2 GB → roughly 1 GB. The every-2-minutes ingest job stops writing 190k
rows/day, freeing Celery CPU on the Mac. Aggregate queries over `events` stop scanning 10M
rows, which is what makes PR 3 cheap.

### PR 3 — Server-side stats

New `GET /events/stats?days=30` returning `{total, countries, sources, spark[]}` computed in
Postgres. `WorldStatusPanel` reads that endpoint instead of `worldStats(events)`, so the
header shows true counts at constant client memory, and the sparkline becomes a server-side
hourly `GROUP BY` rather than a client-side scan of the buffer.

This lands after PR 2 on purpose. Against 10M rows the query measured 80 s and would have
forced a materialized rollup table to be survivable. Against the post-PR-2 table (~450k
rows) it is a plain indexed aggregate, and the rollup machinery is never written.

`CLIENT_LIMITS.eventBuffer` stays where it is, or drops, since it is no longer the source
of any displayed statistic.

### PR 4 — Map spatial bins

New `GET /events/bins?since&zoom` returning rounded lat/lon grid cells with per-cell counts —
on the order of 1–2k rows covering all 456k events. `MapPane` renders weighted circles from
the bins; clicking a cell fetches that cell's individual rows on demand.

Win: the map represents the whole dataset at flat memory cost, instead of showing whichever
slice fit in the buffer.

## Outcome

The header number goes from 7,500 to roughly 456,577 — the real figure — while browser RAM
falls, database size drops by about 6 GB, and ingestion CPU drops. Nothing about the
displayed number is a cap any more.

## Testing

- PR 1: frontend test suite and lint pass with the globe modules gone; `pnpm build`
  succeeds; the map renders and the removed dependencies are absent from the lockfile.
- PR 2: fetcher unit tests cover the aggregation shape; a migration test asserts rollup
  counts match raw counts per country-hour; divergence tests pass against rolled-up input.
- PR 3: API test asserts the endpoint's counts match a direct `SELECT COUNT(*)`; panel test
  asserts the header renders server values rather than buffer length.
- PR 4: API test asserts bin counts sum to the unbinned total for a window; map test asserts
  cell click fetches that cell's rows.
