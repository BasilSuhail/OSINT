import { describe, it, expect, vi, afterEach } from "vitest"
import { fetchEvents, streamUrl } from "./apiClient"

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
})
