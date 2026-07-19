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

/** #340: GDACS/EONET only publish events while they are live, and the fetcher
 *  drops non-current ones at ingest, so a stored row's `is_current` flag can
 *  never be falsified. Feed presence — is the source still re-upserting this
 *  row? — is the only signal that separates "ongoing" from "ended". */
describe("isPersistentActiveHazard feed presence", () => {
  const ongoing = { is_current: true }
  const FEED_LATEST = Date.parse("2026-06-27T11:50:00Z")

  it("keeps a hazard the feed is still republishing", () => {
    const ev = row({ payload: ongoing, fetched_at: "2026-06-27T11:45:00Z" })
    expect(isPersistentActiveHazard(ev, NOW, FEED_LATEST)).toBe(true)
  })

  it("expires a hazard that has dropped out of the feed", () => {
    // Flag still says current — it always will — but the source stopped
    // republishing it days ago, so the event has ended.
    const ev = row({ payload: ongoing, fetched_at: "2026-06-24T09:00:00Z" })
    expect(isPersistentActiveHazard(ev, NOW, FEED_LATEST)).toBe(false)
  })

  it("tolerates missed polls inside the grace window", () => {
    const ev = row({ payload: ongoing, fetched_at: "2026-06-27T09:30:00Z" })
    expect(isPersistentActiveHazard(ev, NOW, FEED_LATEST)).toBe(true)
  })

  it("falls back to the flag when feed freshness is unknown", () => {
    // No fetched_at, or no observed feed activity for the source: refuse to
    // hide data on the strength of missing evidence.
    expect(isPersistentActiveHazard(row({ payload: ongoing }), NOW, FEED_LATEST)).toBe(true)
    expect(
      isPersistentActiveHazard(row({ payload: ongoing, fetched_at: "2026-06-24T09:00:00Z" }), NOW),
    ).toBe(true)
  })

  it("never resurrects a hazard the flag already closed", () => {
    const ev = row({ payload: { is_current: false }, fetched_at: "2026-06-27T11:49:00Z" })
    expect(isPersistentActiveHazard(ev, NOW, FEED_LATEST)).toBe(false)
  })
})
