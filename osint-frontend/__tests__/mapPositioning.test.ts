import { describe, expect, it } from "vitest"
import { isNews, positionForEvent } from "@/lib/mapPositioning"
import type { VisibleEvent } from "@/lib/queries"

const CENTROIDS = new Map<string, [number, number]>([
  ["GB", [-2, 54]],
  ["US", [-98, 39]],
])

function ev(partial: Partial<VisibleEvent>): VisibleEvent {
  return {
    id: 1,
    source: "rss-bbc-uk",
    occurred_at: "2026-07-31T00:00:00Z",
    category: "news",
    country: null,
    lat: null,
    lon: null,
    payload: {},
    ...partial,
  } as unknown as VisibleEvent
}

describe("positionForEvent", () => {
  it("pins a news story on its own coordinates", () => {
    const p = positionForEvent(ev({ lat: 55.95, lon: -3.19, country: "GB" }), CENTROIDS)
    expect(p).toEqual({ lat: 55.95, lon: -3.19 })
  })

  it("pins Edinburgh and Glasgow separately, not once for the UK", () => {
    const edinburgh = positionForEvent(ev({ lat: 55.95, lon: -3.19, country: "GB" }), CENTROIDS)
    const glasgow = positionForEvent(ev({ lat: 55.86, lon: -4.24, country: "GB" }), CENTROIDS)
    expect(edinburgh).not.toEqual(glasgow)
    expect(edinburgh).toEqual({ lat: 55.95, lon: -3.19 })
    expect(glasgow).toEqual({ lat: 55.86, lon: -4.24 })
  })

  it("keeps a foreign outlet's pin — the dot follows the story, not the masthead", () => {
    // SCMP writing about Kyiv carries news_scope "world". It used to be
    // dropped from the pin layer before its coordinates were even read.
    const p = positionForEvent(
      ev({
        source: "rss-scmp-china",
        lat: 50.45,
        lon: 30.52,
        country: "UA",
        payload: { news_scope: "world" },
      }),
      CENTROIDS,
    )
    expect(p).toEqual({ lat: 50.45, lon: 30.52 })
  })

  it("gives a coordless news story no position at all", () => {
    for (const scope of ["local", "world", "unknown"]) {
      const p = positionForEvent(ev({ country: "GB", payload: { news_scope: scope } }), CENTROIDS)
      expect(p, `scope=${scope} must not fall back to a centroid`).toBeNull()
    }
  })

  it("never puts a news story on a country centroid", () => {
    const p = positionForEvent(ev({ country: "US", payload: { news_scope: "local" } }), CENTROIDS)
    expect(p).toBeNull()
  })

  it("still falls back to the centroid for a coordless hazard", () => {
    const p = positionForEvent(
      ev({ source: "gdacs", category: "hazard", country: "GB" }),
      CENTROIDS,
    )
    expect(p).toEqual({ lat: 54, lon: -2 })
  })

  it("drops anything with neither coordinates nor a known country", () => {
    expect(positionForEvent(ev({ source: "gdacs", category: "hazard" }), CENTROIDS)).toBeNull()
    expect(
      positionForEvent(ev({ source: "gdacs", category: "hazard", country: "ZZ" }), CENTROIDS),
    ).toBeNull()
  })
})

describe("isNews", () => {
  it("counts the news category and any rss source", () => {
    expect(isNews(ev({ category: "news", source: "whatever" }))).toBe(true)
    expect(isNews(ev({ category: "geopolitical", source: "rss-tass-en" }))).toBe(true)
  })

  it("does not count hazards or market rows", () => {
    expect(isNews(ev({ category: "hazard", source: "usgs-quake" }))).toBe(false)
    expect(isNews(ev({ category: "market", source: "yfinance" }))).toBe(false)
  })
})
