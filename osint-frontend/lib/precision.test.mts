import { describe, expect, it } from "vitest"
import { PRECISION_LABEL, PRECISION_OPACITY, PRECISION_RADIUS_PX, precisionOf } from "./precision"
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
  it("draws a vaguer claim wider", () => {
    expect(PRECISION_RADIUS_PX.exact).toBeLessThan(PRECISION_RADIUS_PX.city)
    expect(PRECISION_RADIUS_PX.city).toBeLessThan(PRECISION_RADIUS_PX.area)
    expect(PRECISION_RADIUS_PX.area).toBeLessThan(PRECISION_RADIUS_PX.country)
  })

  it("keeps only the verified point solid", () => {
    expect(PRECISION_OPACITY.exact).toBe(1)
    for (const key of ["city", "area", "country", "unknown"] as const) {
      expect(PRECISION_OPACITY[key]).toBeLessThan(1)
    }
  })

  it("says it in words a reader can act on", () => {
    expect(PRECISION_LABEL.city).toMatch(/city/)
    expect(PRECISION_LABEL.exact).toMatch(/verified/)
    expect(PRECISION_LABEL.unknown).not.toMatch(/exact/)
  })
})
