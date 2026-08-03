import { describe, expect, it } from "vitest"
import { mergeEventRows } from "./eventMerge"
import type { EventRow } from "./types"

function row(id: string, updated_at: string, lon: number): EventRow {
  return {
    id,
    source: "rss-test",
    source_event_id: id,
    occurred_at: "2026-08-03T12:00:00Z",
    fetched_at: updated_at,
    updated_at,
    category: "news",
    severity: 0.2,
    keywords: [],
    country: "GB",
    lat: 55.95,
    lon,
    payload: {},
  }
}

describe("mergeEventRows", () => {
  it("keeps a newer live revision over a stale viewport snapshot", () => {
    const live = row("1", "2026-08-03T12:00:00.123456+00:00", -3.18)
    const staleViewport = row("1", "2026-08-03T12:00:00.123455+00:00", -3.20)

    expect(mergeEventRows([live], [staleViewport])).toEqual([live])
  })

  it("accepts a newer viewport revision and adds viewport-only rows", () => {
    const old = row("1", "2026-08-03T12:00:00Z", -3.20)
    const fresh = row("1", "2026-08-03T12:01:00Z", -3.18)
    const localOnly = row("2", "2026-08-03T12:00:00Z", -3.19)

    expect(mergeEventRows([old], [fresh, localOnly])).toEqual([fresh, localOnly])
  })
})
