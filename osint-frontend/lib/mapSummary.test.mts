import { describe, expect, it } from "vitest"
import { mapSummary } from "./mapSummary"
import type { EventRow } from "./types"

function ev(over: Partial<EventRow>): EventRow {
  return {
    id: "e1",
    source: "rss-bbc",
    source_event_id: "x",
    occurred_at: "2026-08-10T00:00:00Z",
    fetched_at: null,
    category: "news",
    severity: 0.4,
    keywords: [],
    country: "GB",
    lat: 51,
    lon: 0,
    payload: {},
    ...over,
  } as EventRow
}

describe("mapSummary", () => {
  it("counts non-hazards by their source", () => {
    const chips = mapSummary([ev({ id: "1" }), ev({ id: "2" }), ev({ id: "3", source: "abuse-ch-x", category: "cyber" })])
    expect(chips.map((c) => [c.label, c.count])).toEqual([
      ["News (RSS)", 2],
      ["Cyber threats", 1],
    ])
  })

  it("counts hazards by disaster type, not by their lump-sum source", () => {
    const quake = ev({ id: "q", source: "usgs-quake", category: "hazard", payload: { magnitude: 5 } })
    const flood = ev({ id: "f", source: "gdacs", category: "hazard", payload: { event_type: "FL" } })
    const chips = mapSummary([quake, flood])
    expect(chips.map((c) => c.label).sort()).toEqual(["Earthquakes", "Floods"])
  })

  it("orders by count, ties alphabetical", () => {
    const chips = mapSummary([
      ev({ id: "a", source: "abuse-ch-x", category: "cyber" }),
      ev({ id: "b" }),
      ev({ id: "c", source: "gdelt", category: "geopolitical" }),
    ])
    expect(chips.map((c) => c.count)).toEqual([1, 1, 1])
    expect(chips.map((c) => c.label)).toEqual(["Cyber threats", "Geopolitical events", "News (RSS)"])
  })

  it("leaves out kinds with nothing on the map", () => {
    const chips = mapSummary([ev({ id: "1" })])
    expect(chips).toHaveLength(1)
    expect(chips.every((c) => c.count > 0)).toBe(true)
  })

  it("carries the colour the map draws that kind in", () => {
    const [chip] = mapSummary([ev({ id: "q", source: "usgs-quake", category: "hazard", payload: { magnitude: 5 } })])
    expect(chip.hex).toBe("#ef4444")
  })

  it("counts nothing for an empty map", () => {
    expect(mapSummary([])).toEqual([])
  })
})
