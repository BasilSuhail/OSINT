import { describe, expect, it } from "vitest"
import { isPersistentActiveHazard } from "@/lib/hazardActivity"
import type { EventRow } from "@/lib/types"

const NOW = Date.parse("2026-06-27T12:00:00Z")

function row(over: Partial<EventRow> = {}): EventRow {
  return {
    id: "x",
    source: "gdacs",
    source_event_id: "TC:1",
    occurred_at: "2026-03-23T00:00:00Z",
    fetched_at: null,
    category: "hazard",
    severity: 0.2,
    keywords: [],
    country: "NC",
    lat: -23.6,
    lon: 163.8,
    payload: {},
    ...over,
  }
}

describe("isPersistentActiveHazard", () => {
  it("keeps explicit current GDACS hazards persistent", () => {
    expect(isPersistentActiveHazard(row({ payload: { is_current: true } }), NOW)).toBe(true)
  })

  it("drops explicit closed GDACS hazards from persistent display", () => {
    expect(isPersistentActiveHazard(row({ payload: { is_current: false } }), NOW)).toBe(false)
  })

  it("treats old pre-flag GDACS rows as expired after to_date grace", () => {
    expect(
      isPersistentActiveHazard(row({ payload: { to_date: "2026-03-24T00:00:00" } }), NOW),
    ).toBe(false)
  })

  it("keeps fresh pre-flag GDACS rows during the grace window", () => {
    expect(
      isPersistentActiveHazard(row({ payload: { to_date: "2026-06-27T00:00:00" } }), NOW),
    ).toBe(true)
  })

  it("keeps open EONET hazards persistent but not closed ones", () => {
    expect(
      isPersistentActiveHazard(row({ source: "eonet", payload: { closed: null } }), NOW),
    ).toBe(true)
    expect(
      isPersistentActiveHazard(
        row({ source: "eonet", payload: { closed: "2026-06-01T00:00:00Z" } }),
        NOW,
      ),
    ).toBe(false)
  })

  it("does not mark USGS point events as persistent", () => {
    expect(isPersistentActiveHazard(row({ source: "usgs-quake" }), NOW)).toBe(false)
  })
})
