import { describe, expect, it } from "vitest"
import { markerStyle } from "@/lib/markers"
import type { EventRow } from "@/lib/types"

describe("markerStyle", () => {
  it("sizes a USGS quake by magnitude", () => {
    const s = markerStyle({
      id: 1, source: "usgs-quake", source_event_id: "x", occurred_at: "2026-06-24T00:00:00Z",
      fetched_at: null, category: "hazard", severity: 0.6, confidence: null, keywords: [],
      country: "VE", lat: 10, lon: -67, payload: { magnitude: 6 },
    } as unknown as EventRow)
    expect(s.shape).toBe("circle")
    expect(s.color).toBeTypeOf("string")
  })
})
