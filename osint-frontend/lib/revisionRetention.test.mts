import { describe, expect, it } from "vitest"
import { EventBuffer } from "./realtime"
import type { EventRow } from "./types"

/** Migration 0026 stamped 1,489,591 rows with one revision, and the live table
 *  still carries that tie. Those rows are ancient; the stamp is not. */
const MIGRATION_STAMP = "2026-08-03T14:31:50.272366Z"

const row = (over: Partial<EventRow>): EventRow =>
  ({
    id: "x",
    source: "rss-bbc-uk",
    source_event_id: "s1",
    occurred_at: "2026-08-01T00:00:00Z",
    fetched_at: null,
    updated_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: [],
    country: "GB",
    lat: 55.9,
    lon: -3.2,
    payload: { title: "story" },
    ...over,
  }) as EventRow

/** Fill past the buffer cap with live rows.
 *
 * Dated *before* the migration stamp on purpose: that is the case where the
 * defect bites. A bulk-stamped row scores as revised on 2026-08-03, so under a
 * plain `max()` it outranks every one of these and takes their place. */
const recentFlood = (n: number): EventRow[] =>
  Array.from({ length: n }, (_, i) =>
    row({
      id: `flood-${i}`,
      source_event_id: `flood-${i}`,
      occurred_at: new Date(Date.UTC(2026, 7, 1, 0, 0, i % 60)).toISOString(),
    }),
  )

describe("buffer retention under a migration-sized revision tie (#764)", () => {
  it("does not let a bulk-stamped ancient row evict a recent one", () => {
    const buffer = new EventBuffer()
    const ancient = row({
      id: "ancient",
      source_event_id: "ancient",
      // Old news, carrying the migration's revision rather than its own.
      occurred_at: "2026-01-04T00:00:00Z",
      updated_at: MIGRATION_STAMP,
    })
    buffer.ingest([ancient, ...recentFlood(9000)])
    const kept = new Set(buffer.getSnapshot().map((e) => e.id))
    expect(kept.has("ancient")).toBe(false)
    // The harm this issue names: a live row losing its place to a backfill.
    // Every surviving row should be one, so the buffer holds live data only.
    expect([...kept].every((id) => id.startsWith("flood-"))).toBe(true)
  })

  it("still keeps a story enriched while the client was watching", () => {
    // The #763 behaviour this must not undo: enrichment can move an older
    // story onto a verified building, and that row has to survive.
    const buffer = new EventBuffer()
    const enriched = row({
      id: "enriched",
      source_event_id: "enriched",
      occurred_at: "2026-01-04T00:00:00Z",
      updated_at: new Date(Date.now() + 1000).toISOString(),
    })
    buffer.ingest([enriched, ...recentFlood(9000)])
    const kept = new Set(buffer.getSnapshot().map((e) => e.id))
    expect(kept.has("enriched")).toBe(true)
  })

  it("keeps an explicitly protected row whatever its revision says", () => {
    const buffer = new EventBuffer()
    const protectedRow = row({
      id: "protected",
      source_event_id: "protected",
      occurred_at: "2026-01-04T00:00:00Z",
      updated_at: MIGRATION_STAMP,
    })
    buffer.ingest([protectedRow, ...recentFlood(9000)], new Set(["protected"]))
    const kept = new Set(buffer.getSnapshot().map((e) => e.id))
    expect(kept.has("protected")).toBe(true)
  })

  it("keeps the newest events when the flood alone overflows", () => {
    const buffer = new EventBuffer()
    buffer.ingest(recentFlood(9000))
    const snapshot = buffer.getSnapshot()
    expect(snapshot.length).toBeLessThanOrEqual(7500)
    expect(snapshot.length).toBeGreaterThan(0)
  })
})
