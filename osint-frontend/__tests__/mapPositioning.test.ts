import { describe, expect, it } from "vitest"
import {
  hasPlaceLevelCoords,
  isNews,
  markerFamily,
  mergeSamePlace,
  padBounds,
  placeName,
  positionForEvent,
  shareBudget,
  withinBounds,
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

describe("shareBudget", () => {
  it("does not let a large family zero out a smaller one", () => {
    // The #721 shape: news arrives newer, GDELT in a daily batch.
    const news = Array.from({ length: 330 }, (_, i) => `news${i}`)
    const gdelt = Array.from({ length: 637 }, (_, i) => `gdelt${i}`)
    const out = shareBudget(new Map([["news", news], ["gdelt", gdelt]]), 280)
    const drawnGdelt = out.filter((x) => x.startsWith("gdelt")).length
    expect(out).toHaveLength(280)
    expect(drawnGdelt).toBeGreaterThan(0)
    // Roughly even, rather than one family taking everything.
    expect(drawnGdelt).toBeGreaterThan(100)
  })

  it("keeps each family's own order — newest first within a family", () => {
    const out = shareBudget(new Map([["a", ["a0", "a1", "a2"]], ["b", ["b0", "b1"]]]), 10)
    expect(out.filter((x) => x.startsWith("a"))).toEqual(["a0", "a1", "a2"])
    expect(out.filter((x) => x.startsWith("b"))).toEqual(["b0", "b1"])
  })

  it("gives a short family's unused share back to the others", () => {
    const out = shareBudget(new Map([["a", ["a0"]], ["b", ["b0", "b1", "b2", "b3"]]]), 5)
    expect(out).toHaveLength(5)
    expect(out.filter((x) => x.startsWith("b"))).toHaveLength(4)
  })

  it("spends the whole budget when there is enough to draw", () => {
    const big = Array.from({ length: 500 }, (_, i) => `x${i}`)
    expect(shareBudget(new Map([["x", big]]), 200)).toHaveLength(200)
  })

  it("returns everything when the budget exceeds what is available", () => {
    const out = shareBudget(new Map([["a", ["a0", "a1"]], ["b", ["b0"]]]), 999)
    expect(out).toHaveLength(3)
  })

  it("handles an exhausted or empty budget without looping", () => {
    expect(shareBudget(new Map([["a", ["a0"]]]), 0)).toEqual([])
    expect(shareBudget(new Map([["a", ["a0"]]]), -5)).toEqual([])
    expect(shareBudget(new Map(), 100)).toEqual([])
    expect(shareBudget(new Map([["a", []]]), 100)).toEqual([])
  })
})

describe("markerFamily", () => {
  it("separates GDELT from news so they cannot starve each other", () => {
    expect(markerFamily(ev({ source: "gdelt", category: "geopolitical" }))).toBe("gdelt")
    expect(markerFamily(ev({ source: "rss-bbc-uk", category: "news" }))).toBe("news")
    expect(markerFamily(ev({ source: "rss-tass-en", category: "news" }))).toBe("news")
  })

  it("keeps other clusterable sources in their own family", () => {
    expect(markerFamily(ev({ source: "uk-police", category: "crime" }))).toBe("uk-police")
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

describe("withinBounds", () => {
  const uk = { west: -11, south: 49, east: 2, north: 61 }

  it("keeps points inside and drops points outside", () => {
    expect(withinBounds(55.95, -3.19, uk)).toBe(true) // Edinburgh
    expect(withinBounds(51.5, -0.12, uk)).toBe(true) // London
    expect(withinBounds(48.86, 2.35, uk)).toBe(false) // Paris — south of the box
    expect(withinBounds(40.42, -3.7, uk)).toBe(false) // Madrid
  })

  it("handles a viewport crossing the antimeridian", () => {
    // MapLibre reports west > east here; the longitude test must be an OR.
    const pacific = { west: 170, south: -20, east: -170, north: 20 }
    expect(withinBounds(-18, 178, pacific)).toBe(true) // Fiji
    expect(withinBounds(0, -175, pacific)).toBe(true)
    expect(withinBounds(0, 0, pacific)).toBe(false) // opposite side of the world
    expect(withinBounds(0, 100, pacific)).toBe(false)
  })

  it("lets everything through once the box spans the globe", () => {
    const world = { west: -200, south: -90, east: 200, north: 90 }
    expect(withinBounds(0, 0, world)).toBe(true)
    expect(withinBounds(-33.9, 151.2, world)).toBe(true)
    expect(withinBounds(64, -21, world)).toBe(true)
  })

  it("rejects on latitude regardless of longitude", () => {
    expect(withinBounds(80, -3, uk)).toBe(false)
    expect(withinBounds(10, -3, uk)).toBe(false)
  })
})

describe("padBounds", () => {
  it("grows the box by a fraction of its own size", () => {
    const p = padBounds({ west: -10, south: 50, east: 0, north: 60 }, 0.25)
    expect(p.west).toBeCloseTo(-12.5)
    expect(p.east).toBeCloseTo(2.5)
    expect(p.south).toBeCloseTo(47.5)
    expect(p.north).toBeCloseTo(62.5)
  })

  it("keeps latitude inside the poles", () => {
    const p = padBounds({ west: -10, south: -88, east: 10, north: 88 }, 0.5)
    expect(p.south).toBe(-90)
    expect(p.north).toBe(90)
  })

  it("pads a box that crosses the antimeridian by its true width", () => {
    // 170 to -170 is 20 degrees wide, not 340.
    const p = padBounds({ west: 170, south: -10, east: -170, north: 10 }, 0.25)
    expect(p.west).toBeCloseTo(165)
    expect(p.east).toBeCloseTo(-165)
  })

  it("admits a point just outside the raw viewport, so panning does not flicker", () => {
    const raw = { west: -11, south: 49, east: 2, north: 61 }
    const justOutside = { lat: 62, lon: 0 }
    expect(withinBounds(justOutside.lat, justOutside.lon, raw)).toBe(false)
    expect(withinBounds(justOutside.lat, justOutside.lon, padBounds(raw))).toBe(true)
  })
})

describe("mergeSamePlace", () => {
  const at = (lat: number, lon: number, place: string | null, key = "geo_name") =>
    ({
      ev: ev({ payload: place ? { [key]: place } : {} }),
      lat,
      lon,
    })

  it("merges one city that two sources place slightly differently", () => {
    // GDELT's London and the gazetteer's London, 250m apart.
    const groups = mergeSamePlace([
      at(51.5, -0.117, "London, London, City of, United Kingdom"),
      at(51.502, -0.119, null, "city"),
    ])
    // second row names London via payload.city
    const named = mergeSamePlace([
      at(51.5, -0.117, "London, London, City of, United Kingdom"),
      { ev: ev({ payload: { city: "London" } }), lat: 51.502, lon: -0.119 },
    ])
    expect(named).toHaveLength(1)
    expect(named[0]).toHaveLength(2)
    expect(groups.length).toBeGreaterThan(0)
  })

  it("keeps a different place in the same city apart", () => {
    // Twickenham is 20km from London. A radius wide enough to merge
    // London's own spread would have swallowed it.
    const groups = mergeSamePlace([
      at(51.5, -0.117, "London, London, City of, United Kingdom"),
      at(51.433, -0.317, "Twickenham, Richmond, United Kingdom"),
      at(51.5, -0.067, "Bermondsey, Southwark, United Kingdom"),
    ])
    expect(groups).toHaveLength(3)
  })

  it("keeps same-named places in different regions apart", () => {
    // There are many Springfields.
    const groups = mergeSamePlace([
      at(39.8, -89.65, "Springfield, Illinois, United States"),
      at(42.1, -72.59, "Springfield, Massachusetts, United States"),
      at(37.21, -93.29, "Springfield, Missouri, United States"),
    ])
    expect(groups).toHaveLength(3)
  })

  it("never merges rows that name no place", () => {
    // Without a name there is no evidence they are the same place, even
    // sitting on the same coordinate.
    const groups = mergeSamePlace([at(51.5, -0.117, null), at(51.5, -0.117, null)])
    expect(groups).toHaveLength(2)
  })

  it("puts the merged mark on the first member's coordinate", () => {
    const groups = mergeSamePlace([
      at(51.5, -0.117, "London, London, City of, United Kingdom"),
      at(51.502, -0.119, "London, Greater London, United Kingdom"),
    ])
    expect(groups[0][0].lat).toBe(51.5)
  })
})

describe("placeName", () => {
  it("takes the settlement from a GDELT full name", () => {
    expect(placeName(ev({ payload: { geo_name: "Tehran, Tehran, Iran" } }))).toBe("tehran")
  })
  it("falls back to a news row's city", () => {
    expect(placeName(ev({ payload: { city: "Karachi" } }))).toBe("karachi")
  })
  it("is null when the row names nowhere", () => {
    expect(placeName(ev({ payload: {} }))).toBeNull()
  })
})
