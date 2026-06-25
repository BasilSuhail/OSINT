import { describe, expect, it } from "vitest"
import { markerStyle } from "@/lib/markers"
import type { EventRow } from "@/lib/types"

function row(partial: Partial<EventRow>): EventRow {
  return {
    id: 1,
    source: "usgs-quake",
    source_event_id: "x",
    occurred_at: "2026-06-24T22:04:00Z",
    category: "hazard",
    severity: 0.6,
    confidence: null,
    keywords: [],
    country: "VE",
    lat: 10,
    lon: -67,
    payload: {},
    ...partial,
  } as EventRow
}

describe("markerStyle earthquake emphasis ring", () => {
  it("rings a strong USGS quake (M >= 4.5)", () => {
    const s = markerStyle(row({ source: "usgs-quake", payload: { magnitude: 6.1 } }))
    expect(s.ring).toBe(true)
  })

  it("does not ring a minor USGS quake", () => {
    const s = markerStyle(row({ source: "usgs-quake", payload: { magnitude: 2.3 } }))
    expect(s.ring).toBe(false)
  })

  it("rings an orange GDACS earthquake regardless of magnitude", () => {
    const s = markerStyle(
      row({
        source: "gdacs",
        payload: { event_type: "EQ", alert_level: "Orange", magnitude: 2.3 },
      }),
    )
    expect(s.ring).toBe(true)
  })

  it("does not ring a non-earthquake GDACS hazard", () => {
    const s = markerStyle(
      row({ source: "gdacs", payload: { event_type: "TC", alert_level: "Orange" } }),
    )
    expect(s.ring).toBe(false)
  })

  it("does not ring non-quake sources", () => {
    const s = markerStyle(row({ source: "rss-bbc-world", category: "news", payload: {} }))
    expect(s.ring).toBe(false)
  })
})
