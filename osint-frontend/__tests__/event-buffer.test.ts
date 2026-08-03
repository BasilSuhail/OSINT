import { describe, expect, it } from "vitest"

import { EventBuffer } from "@/lib/realtime"
import { CLIENT_LIMITS } from "@/lib/apiClient"
import type { EventRow } from "@/lib/types"

function row(over: Partial<EventRow> = {}): EventRow {
  return {
    id: "x",
    source: "rss-bbc-world",
    source_event_id: null,
    occurred_at: new Date().toISOString(),
    fetched_at: null,
    updated_at: null,
    category: "news",
    severity: 0.5,
    keywords: null,
    country: "GB",
    lat: null,
    lon: null,
    payload: {},
    ...over,
  }
}

describe("EventBuffer.ingest source filtering", () => {
  it("advances revision cursor only from incremental pages", () => {
    const buf = new EventBuffer()
    buf.ingest([row({ id: "99", updated_at: "2026-08-03T12:00:00Z" })])
    expect(buf.getRevisionCursor()).toBeNull()

    buf.ingestUpdated([
      row({ id: "41", updated_at: "2026-08-03T11:00:00Z" }),
      row({ id: "42", updated_at: "2026-08-03T11:00:00Z" }),
    ])
    expect(buf.getRevisionCursor()).toEqual({
      updatedAt: "2026-08-03T11:00:00Z",
      id: "42",
    })
  })

  it("preserves microseconds so equal-timestamp pages can advance by ID", () => {
    const buf = new EventBuffer()
    buf.ingestUpdated([
      row({ id: "41", updated_at: "2026-08-03T11:00:00.123456+00:00" }),
      row({ id: "42", updated_at: "2026-08-03T11:00:00.123456+00:00" }),
    ])
    expect(buf.getRevisionCursor()).toEqual({
      updatedAt: "2026-08-03T11:00:00.123456+00:00",
      id: "42",
    })
  })

  it("retains an older row delivered by revision polling when the buffer is full", () => {
    const buf = new EventBuffer()
    const occurred = "2026-08-03T11:00:00Z"
    buf.ingest(
      Array.from({ length: CLIENT_LIMITS.eventBuffer }, (_, index) =>
        row({ id: String(index + 1), occurred_at: occurred }),
      ),
    )

    buf.ingestUpdated([
      row({
        id: "999999",
        occurred_at: "2026-07-01T11:00:00Z",
        updated_at: "2026-08-03T12:00:00.123456+00:00",
        payload: { geo_basis: "place", place_name: "Old Bailey" },
      }),
    ])

    expect(buf.getSnapshot().some((event) => event.id === "999999")).toBe(true)
  })

  it("does not roll back revisions within one JavaScript millisecond", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({
        id: "place",
        updated_at: "2026-08-03T11:00:00.123456+00:00",
        lat: 51.5156,
        lon: -0.1019,
      }),
    ])
    buf.ingest([
      row({
        id: "place",
        updated_at: "2026-08-03T11:00:00.123123+00:00",
        lat: 51.5072,
        lon: -0.1276,
      }),
    ])

    expect([buf.getSnapshot()[0]?.lat, buf.getSnapshot()[0]?.lon]).toEqual([51.5156, -0.1019])
  })

  it("keeps events that map to a source toggle", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "1", source: "gdelt", category: "geopolitical" }),
      row({ id: "2", source: "rss-bbc-world", category: "news" }),
    ])
    expect(buf.getSnapshot()).toHaveLength(2)
  })

  it("drops NASA FIRMS thermal pixels rather than tagging them GDACS", () => {
    // FIRMS rows carry category "hazard". Once the globe (their only renderer)
    // was removed in #494, sourceKeyForEvent must return null for them — if it
    // fell through to the category fallback they would surface as GDACS and
    // put ~390k fire pixels on the map.
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "1", source: "nasa-firms", category: "hazard" }),
      row({ id: "2", source: "gdacs", category: "hazard" }),
    ])
    const snap = buf.getSnapshot()
    expect(snap).toHaveLength(1)
    expect(snap[0]?.source).toBe("gdacs")
  })

  it("drops the opensky-adsb aviation firehose (no source toggle)", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "1", source: "opensky-adsb", category: "tracking" }),
      row({ id: "2", source: "opensky-adsb", category: "tracking" }),
    ])
    expect(buf.getSnapshot()).toHaveLength(0)
  })

  it("does not let aviation evict displayable events", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "keep", source: "gdelt", category: "geopolitical" }),
      ...Array.from({ length: 100 }, (_, i) =>
        row({ id: `adsb-${i}`, source: "opensky-adsb", category: "tracking" }),
      ),
    ])
    const snap = buf.getSnapshot()
    expect(snap).toHaveLength(1)
    expect(snap[0]?.id).toBe("keep")
  })

  it("replaces a same-ID row when its position and provenance refresh", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({
        id: "place",
        fetched_at: "2026-08-03T11:00:00Z",
        lat: 55.9483,
        lon: -3.2191,
        payload: { geo_basis: "city", city: "Edinburgh" },
      }),
    ])

    buf.ingest([
      row({
        id: "place",
        fetched_at: "2026-08-03T11:00:00Z",
        updated_at: "2026-08-03T11:05:00Z",
        lat: 55.9418715963841,
        lon: -3.20281137653343,
        payload: {
          geo_basis: "place",
          place_name: "King's Theatre",
          place_wikidata_id: "Q6411122",
        },
      }),
    ])

    const snap = buf.getSnapshot()
    expect(snap).toHaveLength(1)
    expect([snap[0]?.lat, snap[0]?.lon]).toEqual([55.9418715963841, -3.20281137653343])
    expect(snap[0]?.payload).toMatchObject({
      geo_basis: "place",
      place_wikidata_id: "Q6411122",
    })
  })

  it("does not let an older overlapping response revert refreshed coordinates", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({
        id: "place",
        fetched_at: "2026-08-03T11:00:00Z",
        lat: 55.9418715963841,
        lon: -3.20281137653343,
        updated_at: "2026-08-03T11:05:00Z",
        payload: { geo_basis: "place", place_name: "King's Theatre" },
      }),
    ])

    buf.ingest([
      row({
        id: "place",
        fetched_at: "2026-08-03T11:00:00Z",
        updated_at: "2026-08-03T11:00:00Z",
        lat: 55.9483,
        lon: -3.2191,
        payload: { geo_basis: "city", city: "Edinburgh" },
      }),
    ])

    const snap = buf.getSnapshot()
    expect(snap).toHaveLength(1)
    expect([snap[0]?.lat, snap[0]?.lon]).toEqual([55.9418715963841, -3.20281137653343])
    expect(snap[0]?.payload).toMatchObject({
      geo_basis: "place",
      place_name: "King's Theatre",
    })
  })
})
