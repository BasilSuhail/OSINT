import { describe, it, expect, vi, afterEach } from "vitest"
import {
  CLIENT_LIMITS,
  fetchAllEventPages,
  fetchAllUpdatedEventPages,
  fetchEvents,
  fetchIngestHealth,
  fetchScores,
  streamUrl,
} from "./apiClient"
import type { EventRow } from "./types"

afterEach(() => vi.restoreAllMocks())

describe("apiClient", () => {
  it("builds the events query string", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchEvents({ exclude: ["opensky-adsb"], limit: 100 })
    const url = (spy.mock.calls[0][0] as string)
    expect(url).toContain("/events?")
    expect(url).toContain("exclude=opensky-adsb")
    expect(url).toContain("limit=100")
  })

  it("exposes the stream url", () => {
    expect(streamUrl()).toMatch(/\/stream$/)
  })

  it("passes incremental timestamps and country as query params", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchEvents({
      fetchedSince: "2026-06-26T00:00:00Z",
      updatedSince: "2026-06-27T00:00:00Z",
      updatedAfterId: "42",
      country: "US",
    })
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain("fetched_since=")
    expect(url).toContain("updated_since=")
    expect(url).toContain("updated_after_id=42")
    expect(url).toContain("country=US")
  })

  it("passes viewport, time, and occurrence cursor params", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchEvents({
      since: "2026-08-01T00:00:00Z",
      until: "2026-08-03T00:00:00Z",
      occurredBefore: "2026-08-02T00:00:00Z",
      occurredBeforeId: "42",
      west: -3.4,
      south: 55.8,
      east: -3.0,
      north: 56.1,
      positionedOnly: true,
    })
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain("since=")
    expect(url).toContain("until=")
    expect(url).toContain("occurred_before=")
    expect(url).toContain("occurred_before_id=42")
    expect(url).toContain("west=-3.4")
    expect(url).toContain("south=55.8")
    expect(url).toContain("east=-3")
    expect(url).toContain("north=56.1")
    expect(url).toContain("positioned_only=true")
  })

  it("pages through every row in a bounded viewport", async () => {
    const row = (id: string, occurred_at: string): EventRow => ({
      id,
      source: "gdelt",
      source_event_id: id,
      occurred_at,
      fetched_at: occurred_at,
      category: "news",
      severity: 0.2,
      keywords: [],
      country: "GB",
      lat: 55.95,
      lon: -3.19,
      payload: {},
    })
    const pages = [
      [row("3", "2026-08-03T12:00:00Z"), row("2", "2026-08-03T11:00:00Z")],
      [row("1", "2026-08-03T10:00:00Z")],
    ]
    const spy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(pages[0]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(pages[1]), { status: 200 }))
    const controller = new AbortController()

    const rows = await fetchAllEventPages({
      west: -3.4,
      south: 55.8,
      east: -3.0,
      north: 56.1,
      positionedOnly: true,
    }, 2, { signal: controller.signal })

    expect(rows.map(({ id }) => id)).toEqual(["3", "2", "1"])
    expect(spy).toHaveBeenCalledTimes(2)
    const secondUrl = spy.mock.calls[1][0] as string
    expect(secondUrl).toContain("occurred_before=")
    expect(secondUrl).toContain("occurred_before_id=2")
    expect(spy.mock.calls[0][1]).toMatchObject({ signal: controller.signal })
    expect(spy.mock.calls[1][1]).toMatchObject({ signal: controller.signal })
  })

  it("pages late viewport revisions with the durable update cursor", async () => {
    const row = (id: string, updated_at: string): EventRow => ({
      id,
      source: "rss-test",
      source_event_id: id,
      occurred_at: "2026-08-03T10:00:00Z",
      fetched_at: updated_at,
      updated_at,
      category: "news",
      severity: 0.2,
      keywords: [],
      country: "GB",
      lat: 55.95,
      lon: -3.19,
      payload: {},
    })
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            row("1", "2026-08-03T12:00:00.000001Z"),
            row("2", "2026-08-03T12:00:00.000001Z"),
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([row("3", "2026-08-03T12:01:00Z")]), { status: 200 }),
      )

    const rows = await fetchAllUpdatedEventPages(
      { west: -3.4, south: 55.8, east: -3, north: 56.1 },
      "2026-08-03T11:59:00Z",
      2,
    )

    expect(rows.map(({ id }) => id)).toEqual(["1", "2", "3"])
    const secondUrl = spy.mock.calls[1][0] as string
    expect(secondUrl).toContain("updated_since=")
    expect(secondUrl).toContain("updated_after_id=2")
  })

  it("fetches ingest health with days param", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchIngestHealth(7)
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain("/ingest-health?")
    expect(url).toContain("days=7")
  })

  it("builds score filter query params", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchScores({
      scoreName: "cii_v1",
      since: "2026-06-01T00:00:00Z",
      country: "US",
      limit: 200,
    })
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain("/scores?")
    expect(url).toContain("score_name=cii_v1")
    expect(url).toContain("since=")
    expect(url).toContain("country=US")
    expect(url).toContain("limit=200")
  })
})

/** The three polls that fill the map buffer asked for 8,500 rows into a buffer
 *  of 7,500, so they evicted each other on every cycle and the sparsest of them
 *  lost. A buffer smaller than what is fetched into it cannot be right. */
describe("CLIENT_LIMITS", () => {
  it("holds everything the polls that fill it ask for", () => {
    const fetched =
      CLIENT_LIMITS.eventWindow + CLIENT_LIMITS.hazardEvents + CLIENT_LIMITS.cyberEvents
    expect(CLIENT_LIMITS.eventBuffer).toBeGreaterThanOrEqual(fetched)
  })
})
