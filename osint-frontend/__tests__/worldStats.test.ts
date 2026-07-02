import { describe, expect, it } from "vitest"
import { worldStats } from "@/lib/worldStats"
import type { EventRow } from "@/lib/types"

function ev(over: Partial<EventRow> = {}): EventRow {
  return {
    id: Math.random().toString(36).slice(2),
    source: "rss-bbc-world",
    source_event_id: null,
    occurred_at: "2026-06-30T12:00:00Z",
    fetched_at: null,
    category: "news",
    severity: 0.2,
    keywords: [],
    country: "UA",
    lat: 50,
    lon: 30,
    payload: {},
    ...over,
  }
}

describe("worldStats", () => {
  it("counts totals, distinct countries and sources", () => {
    const s = worldStats([
      ev({ country: "UA", source: "acled" }),
      ev({ country: "UA", source: "rss-bbc-world" }),
      ev({ country: "RU", source: "acled" }),
    ])
    expect(s.total).toBe(3)
    expect(s.activeCountries).toBe(2)
    expect(s.activeSources).toBe(2)
  })

  it("ranks countries by frequency, desc", () => {
    const s = worldStats([
      ev({ country: "UA" }),
      ev({ country: "UA" }),
      ev({ country: "UA" }),
      ev({ country: "RU" }),
      ev({ country: "MX" }),
      ev({ country: "MX" }),
    ])
    expect(s.topCountries[0]).toEqual({ country: "UA", count: 3 })
    expect(s.topCountries[1]).toEqual({ country: "MX", count: 2 })
    expect(s.topCountries[2]).toEqual({ country: "RU", count: 1 })
  })

  it("caps the ranking at topN", () => {
    const events = Array.from({ length: 20 }, (_, i) => ev({ country: `C${i}` }))
    const s = worldStats(events, 5)
    expect(s.topCountries).toHaveLength(5)
  })

  it("ignores events with no country in the ranking but keeps them in total", () => {
    const s = worldStats([ev({ country: null }), ev({ country: "UA" })])
    expect(s.total).toBe(2)
    expect(s.activeCountries).toBe(1)
  })

  it("buckets events across the time span for the sparkline", () => {
    const s = worldStats(
      [
        ev({ occurred_at: "2026-06-01T00:00:00Z" }),
        ev({ occurred_at: "2026-06-30T00:00:00Z" }),
      ],
      12,
      4,
    )
    expect(s.spark).toHaveLength(4)
    expect(s.spark[0]).toBe(1) // oldest bucket
    expect(s.spark[3]).toBe(1) // newest bucket
    expect(s.spark.reduce((a, b) => a + b, 0)).toBe(2)
  })

  it("returns a zero-filled sparkline for an empty buffer", () => {
    const s = worldStats([], 12, 4)
    expect(s.total).toBe(0)
    expect(s.spark).toEqual([0, 0, 0, 0])
    expect(s.topCountries).toEqual([])
  })
})
