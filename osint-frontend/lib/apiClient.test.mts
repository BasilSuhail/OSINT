import { describe, it, expect, vi, afterEach } from "vitest"
import { fetchEvents, fetchIngestHealth, fetchScores, streamUrl } from "./apiClient"

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

  it("passes fetched_since and country as query params", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
    await fetchEvents({ fetchedSince: "2026-06-26T00:00:00Z", country: "US" })
    const url = spy.mock.calls[0][0] as string
    expect(url).toContain("fetched_since=")
    expect(url).toContain("country=US")
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
