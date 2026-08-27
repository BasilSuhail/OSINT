import { describe, expect, it } from "vitest"
import { isPersistentActiveHazard } from "@/lib/hazardActivity"
import type { EventRow } from "@/lib/types"

const NOW = Date.parse("2026-08-27T03:00:00Z")
const FEED_LATEST = Date.parse("2026-08-27T02:50:00Z")

function row(over: Partial<EventRow> = {}): EventRow {
  return {
    id: "x",
    source: "gdacs",
    source_event_id: "FL:1",
    //: Onset a week back — the shape the three-day window cannot hold.
    occurred_at: "2026-08-20T00:00:00Z",
    fetched_at: "2026-08-27T02:45:00Z",
    category: "hazard",
    severity: 0.6,
    keywords: [],
    country: "NP",
    lat: 28,
    lon: 84,
    payload: { is_current: true },
    ...over,
  }
}

describe("what may outlive the window", () => {
  it("keeps an orange flood that began before it and is still running", () => {
    expect(isPersistentActiveHazard(row(), NOW, FEED_LATEST)).toBe(true)
  })

  it("keeps a red one", () => {
    expect(isPersistentActiveHazard(row({ severity: 1 }), NOW, FEED_LATEST)).toBe(true)
  })

  it("keeps a small wildfire its feed is still reporting", () => {
    //: Nothing here decides an event is too routine to draw. A green GDACS
    //: fire the source still lists is running, and whether wildfires are worth
    //: seeing is what the disaster-type filters are for.
    expect(isPersistentActiveHazard(row({ severity: 0.2 }), NOW, FEED_LATEST)).toBe(true)
  })

  it("refuses one that had not started at the moment on screen", () => {
    const scrubbed = Date.parse("2026-07-15T00:00:00Z")
    expect(isPersistentActiveHazard(row(), scrubbed, FEED_LATEST)).toBe(false)
  })

  it("refuses one its feed had already dropped by that moment", () => {
    const ev = row({ fetched_at: "2026-08-21T00:00:00Z" })
    expect(isPersistentActiveHazard(ev, NOW, FEED_LATEST)).toBe(false)
  })

  it("keeps one the feed was still carrying at a past moment", () => {
    //: Onset in June, last seen in August: it was running in July.
    const scrubbed = Date.parse("2026-07-15T00:00:00Z")
    const ev = row({ occurred_at: "2026-06-01T00:00:00Z", fetched_at: "2026-08-01T00:00:00Z" })
    expect(isPersistentActiveHazard(ev, scrubbed, FEED_LATEST)).toBe(true)
  })

  it("never resurrects one the flag has closed", () => {
    expect(isPersistentActiveHazard(row({ payload: { is_current: false } }), NOW, FEED_LATEST))
      .toBe(false)
  })

  it("keeps an open EONET event and drops a closed one", () => {
    const open = row({ source: "eonet", severity: 0.8, payload: { closed: null } })
    const shut = row({ source: "eonet", severity: 0.8, payload: { closed: "2026-08-25T00:00:00Z" } })
    expect(isPersistentActiveHazard(open, NOW, FEED_LATEST)).toBe(true)
    expect(isPersistentActiveHazard(shut, NOW, FEED_LATEST)).toBe(false)
  })

  it("never exempts a quake, which is not a state", () => {
    expect(isPersistentActiveHazard(row({ source: "usgs-quake" }), NOW, FEED_LATEST)).toBe(false)
  })

  it("never exempts something that is not a hazard", () => {
    expect(isPersistentActiveHazard(row({ category: "news" }), NOW, FEED_LATEST)).toBe(false)
  })

  it("does not hide data when feed freshness is unknown", () => {
    expect(isPersistentActiveHazard(row({ fetched_at: null }), NOW, FEED_LATEST)).toBe(true)
    expect(isPersistentActiveHazard(row(), NOW)).toBe(true)
  })
})
