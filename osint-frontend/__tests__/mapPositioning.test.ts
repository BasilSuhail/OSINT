import { describe, expect, it } from "vitest"
import {
  eventPointCollection,
  hasPlaceLevelCoords,
  isNews,
  positionForEvent,
  positionsForEvent,
} from "@/lib/mapPositioning"
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

describe("positionsForEvent", () => {
  it("expands one story into every verified place marker", () => {
    const positions = positionsForEvent(
      ev({
        id: "story",
        lat: 51.5009,
        lon: -0.1774,
        payload: {
          place_locations: [
            {
              name: "Royal Albert Hall",
              wikidata_id: "Q187868",
              lat: 51.5009,
              lon: -0.1774,
            },
            {
              name: "Wembley Stadium",
              wikidata_id: "Q193633",
              lat: 51.556,
              lon: -0.2796,
            },
          ],
        },
      }),
      CENTROIDS,
    )

    expect(positions).toEqual([
      {
        key: "story:wikidata:Q187868",
        lat: 51.5009,
        lon: -0.1774,
        place: "royal albert hall",
        location: {
          checkedAt: null,
          description: null,
          lat: 51.5009,
          lon: -0.1774,
          model: null,
          name: "Royal Albert Hall",
          precision: null,
          source: "wikidata",
          wikidataId: "Q187868",
        },
      },
      {
        key: "story:wikidata:Q193633",
        lat: 51.556,
        lon: -0.2796,
        place: "wembley stadium",
        location: {
          checkedAt: null,
          description: null,
          lat: 51.556,
          lon: -0.2796,
          model: null,
          name: "Wembley Stadium",
          precision: null,
          source: "wikidata",
          wikidataId: "Q193633",
        },
      },
    ])
  })

  it("deduplicates one verified entity and rejects malformed locations", () => {
    const positions = positionsForEvent(
      ev({
        id: "story",
        payload: {
          place_locations: [
            { name: "Kigali Arena", wikidata_id: "Q1", lat: -1.953, lon: 30.1155 },
            { name: "same entity", wikidata_id: "Q1", lat: 0, lon: 0 },
            { name: "invalid", wikidata_id: "Q2", lat: 120, lon: 0 },
          ],
        },
      }),
      CENTROIDS,
    )

    expect(positions).toHaveLength(1)
    expect(positions[0].key).toBe("story:wikidata:Q1")
  })

  it("falls back to the legacy primary coordinate without verified locations", () => {
    expect(
      positionsForEvent(
        ev({ id: "legacy", lat: 55.95, lon: -3.19, payload: { place_locations: [] } }),
        CENTROIDS,
      ),
    ).toEqual([{ key: "legacy", lat: 55.95, lon: -3.19 }])
  })

  it("labels a synthetic hazard point as a country-centroid fallback", () => {
    expect(
      positionsForEvent(
        ev({ id: "hazard", source: "gdacs", category: "hazard", country: "GB" }),
        CENTROIDS,
      ),
    ).toEqual([
      {
        key: "hazard",
        lat: 54,
        lon: -2,
        location: {
          lat: 54,
          lon: -2,
          name: "GB",
          precision: "unknown",
          source: "country-centroid",
        },
      },
    ])
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

describe("eventPointCollection", () => {
  it("retains every valid position without a marker budget", () => {
    const positions = Array.from({ length: 1_200 }, (_, index) => ({
      ev: ev({ id: String(index), lat: 51.5 + index / 100_000, lon: -0.12 }),
      markerKey: `event:${index}`,
      lat: 51.5 + index / 100_000,
      lon: -0.12,
    }))

    const collection = eventPointCollection(positions)

    expect(collection.features).toHaveLength(positions.length)
    expect(new Set(collection.features.map((feature) => feature.properties.markerKey)).size).toBe(
      positions.length,
    )
  })

  it("keeps the original exact coordinate and marker identity", () => {
    const collection = eventPointCollection([
      {
        ev: ev({ id: "7", lat: 55.9418715963841, lon: -3.20281137653343 }),
        markerKey: "7:wikidata:Q6411122",
        lat: 55.9418715963841,
        lon: -3.20281137653343,
      },
    ])

    expect(collection.features[0]?.geometry.coordinates).toEqual([
      -3.20281137653343,
      55.9418715963841,
    ])
    expect(collection.features[0]?.properties.markerKey).toBe("7:wikidata:Q6411122")
  })
})

describe("hasPlaceLevelCoords", () => {
  const gdelt = (payload: Record<string, unknown>) =>
    ev({ source: "gdelt", category: "geopolitical", lat: 60, lon: 100, payload })

  it("keeps a city-level GDELT event", () => {
    expect(hasPlaceLevelCoords(gdelt({ geo_precision: "city" }))).toBe(true)
  })

  it("drops country- and admin-level GDELT events", () => {
    // Their coordinate means "somewhere in Russia" — 10 and 21 such rows
    // stacked on a single point in the measured window.
    expect(hasPlaceLevelCoords(gdelt({ geo_precision: "country" }))).toBe(false)
    expect(hasPlaceLevelCoords(gdelt({ geo_precision: "admin" }))).toBe(false)
    expect(hasPlaceLevelCoords(gdelt({ geo_precision: "unknown" }))).toBe(false)
  })

  it("classifies rows stored before the precision field existed", () => {
    expect(hasPlaceLevelCoords(gdelt({ country_fips: "Tehran, Tehran, Iran" }))).toBe(true)
    expect(hasPlaceLevelCoords(gdelt({ country_fips: "Iran" }))).toBe(false)
    expect(hasPlaceLevelCoords(gdelt({ country_fips: "California, United States" }))).toBe(false)
    expect(hasPlaceLevelCoords(gdelt({}))).toBe(false)
  })

  it("leaves every other source alone", () => {
    // News is held to this standard by the resolver; hazards are coarse by
    // nature and too few to stack.
    expect(hasPlaceLevelCoords(ev({ source: "rss-bbc-uk", category: "news" }))).toBe(true)
    expect(hasPlaceLevelCoords(ev({ source: "gdacs", category: "hazard" }))).toBe(true)
    expect(hasPlaceLevelCoords(ev({ source: "usgs-quake", category: "hazard" }))).toBe(true)
  })

  it("keeps a country-level GDELT row off the map entirely", () => {
    const at = positionForEvent(gdelt({ geo_precision: "country" }), CENTROIDS)
    expect(at).toBeNull()
  })
})
