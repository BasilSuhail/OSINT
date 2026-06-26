import { describe, expect, it } from "vitest"
import { hazardKind, hazardColor, hazardIcon, footprintFeatures } from "@/lib/hazardSymbols"
import type { EventRow } from "@/lib/types"

function row(p: Partial<EventRow>): EventRow {
  return {
    id: 1, source: "gdacs", source_event_id: "x", occurred_at: "2026-06-24T00:00:00Z",
    category: "hazard", severity: 0.5, confidence: null, keywords: [],
    country: "VE", lat: 10, lon: -67, payload: {}, ...p,
  } as EventRow
}

describe("hazardKind", () => {
  it("maps USGS to EQ", () => expect(hazardKind(row({ source: "usgs-quake" }))).toBe("EQ"))
  it("maps FIRMS to WF", () => expect(hazardKind(row({ source: "nasa-firms" }))).toBe("WF"))
  it("reads GDACS event_type", () => {
    expect(hazardKind(row({ payload: { event_type: "TC" } }))).toBe("TC")
    expect(hazardKind(row({ payload: { event_type: "FL" } }))).toBe("FL")
  })
  it("falls back to other", () => expect(hazardKind(row({ source: "gdelt", payload: {} }))).toBe("other"))
})

describe("hazardColor", () => {
  it("uses GDACS alert level", () => {
    expect(hazardColor(row({ payload: { alert_level: "Red" } }))).toBe("#ef4444")
    expect(hazardColor(row({ payload: { alert_level: "Orange" } }))).toBe("#f97316")
    expect(hazardColor(row({ payload: { alert_level: "Green" } }))).toBe("#22c55e")
  })
  it("falls back to USGS magnitude bands", () => {
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 6.4 } }))).toBe("#ef4444")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 5.0 } }))).toBe("#f97316")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 3.0 } }))).toBe("#22c55e")
  })
})

describe("hazardIcon", () => {
  it("maps kind to a lucide key", () => {
    expect(hazardIcon("EQ")).toBe("activity")
    expect(hazardIcon("WF")).toBe("flame")
    expect(hazardIcon("other")).toBe("dot")
  })
})

describe("footprintFeatures", () => {
  it("emits multiple ring features for a strong quake", () => {
    const f = footprintFeatures(row({ source: "usgs-quake", payload: { magnitude: 6.5, depth_km: 10 } }))
    expect(f.length).toBeGreaterThan(1)
    expect(f[0].geometry.type).toBe("Polygon")
    expect(f[0].properties?.color).toBeTypeOf("string")
  })
  it("emits one circle for a fire with a burned area", () => {
    const f = footprintFeatures(row({ payload: { event_type: "WF", severity_raw: "... in 8028 ha", alert_level: "Green" } }))
    expect(f).toHaveLength(1)
  })
  it("emits nothing when there is no usable geometry", () => {
    expect(footprintFeatures(row({ source: "gdelt", payload: {}, lat: null, lon: null }))).toHaveLength(0)
  })
})
