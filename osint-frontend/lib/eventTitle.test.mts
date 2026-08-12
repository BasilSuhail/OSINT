import { describe, expect, it } from "vitest"
import { eventHeadline } from "./eventTitle"
import type { EventRow } from "./types"

function row(over: Partial<EventRow> & { source: string }): EventRow {
  return {
    id: "1",
    source_event_id: null,
    occurred_at: "2026-08-12T10:00:00Z",
    fetched_at: null,
    category: "hazard",
    severity: 0,
    keywords: null,
    country: null,
    lat: null,
    lon: null,
    payload: {},
    ...over,
  } as EventRow
}

describe("eventHeadline for sources that publish no prose", () => {
  it("gives each fire detection its place and power", () => {
    //: Search finds these by keyword now, so forty of them can land in one
    //: list. Forty rows reading "nasa-firms" is not a list of results.
    const a = eventHeadline(row({ source: "nasa-firms", country: "ZA", payload: { frp: "12.4" } }))
    const b = eventHeadline(row({ source: "nasa-firms", country: "AU", payload: { frp: "3.1" } }))
    expect(a).toBe("Fire detection · ZA · 12 MW")
    expect(b).toBe("Fire detection · AU · 3 MW")
    expect(a).not.toBe(b)
  })

  it("says what a quake measured and where", () => {
    const out = eventHeadline(
      row({ source: "usgs-quake", payload: { place: "10 km SW of Ridgecrest", magnitude: 5.24 } }),
    )
    expect(out).toBe("M5.2 earthquake · 10 km SW of Ridgecrest")
  })

  it("falls back to the place when a quake carries no magnitude", () => {
    const out = eventHeadline(row({ source: "usgs-quake", payload: { place: "Off Honshu" } }))
    expect(out).toBe("Earthquake · Off Honshu")
  })

  it("uses the name GDACS gave its event", () => {
    const out = eventHeadline(row({ source: "gdacs", payload: { eventname: "Tropical Cyclone X" } }))
    expect(out).toBe("Tropical Cyclone X")
  })

  it("reads a threat classification as words", () => {
    const out = eventHeadline(
      row({
        source: "abuse-ch-urlhaus",
        category: "cyber",
        payload: { threat: "malware_download", url: "http://evil.example.com/x" },
      }),
    )
    expect(out).toBe("malware download · evil.example.com")
  })

  it("counts the aircraft a tracking sample saw", () => {
    const out = eventHeadline(
      row({ source: "opensky-adsb", category: "tracking", country: "GB", payload: { aircraft_count: 42 } }),
    )
    expect(out).toBe("42 aircraft tracked · GB")
  })

  it("still prefers a real headline over anything synthesised", () => {
    const out = eventHeadline(row({ source: "usgs-quake", payload: { title: "Quake hits city", place: "X" } }))
    expect(out).toBe("Quake hits city")
  })

  it("falls back to the source when the row says nothing at all", () => {
    expect(eventHeadline(row({ source: "rss-bbc-uk" }))).toBe("bbc-uk")
  })
})
