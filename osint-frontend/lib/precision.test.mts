import { describe, expect, it } from "vitest"
import { MARKER_RADIUS_PX, PRECISION_LABEL, precisionOf } from "./precision"
import type { EventRow } from "./types"

const row = (over: Partial<EventRow> = {}): EventRow =>
  ({
    id: "1",
    source: "gdelt",
    source_event_id: "g1",
    occurred_at: "2026-08-08T12:00:00Z",
    fetched_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: [],
    country: "GB",
    lat: 55.95,
    lon: -3.2,
    payload: {},
    ...over,
  }) as EventRow

describe("precisionOf", () => {
  it("uses what the API decided", () => {
    expect(precisionOf(row({ location_precision: "city" }))).toBe("city")
  })

  it("defaults to unknown, never to exact", () => {
    // A row cached before #773 must not imply a precision nobody established.
    expect(precisionOf(row())).toBe("unknown")
  })
})

describe("how a claim is drawn", () => {
  it("draws every claim the same size (#891)", () => {
    // Sizing by vagueness made the least informative point the largest mark
    // on the map, and fading by vagueness on top of the age fade left an
    // empty ring. One radius, small enough that a lone event reads as a dot.
    expect(MARKER_RADIUS_PX).toBeLessThanOrEqual(5)
  })

  it("says it in words a reader can act on", () => {
    expect(PRECISION_LABEL.city).toMatch(/city/)
    expect(PRECISION_LABEL.exact).toMatch(/verified/)
    expect(PRECISION_LABEL.unknown).not.toMatch(/exact/)
  })
})
