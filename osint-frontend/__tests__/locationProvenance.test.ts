import { describe, expect, it } from "vitest"
import {
  locationProvenanceForEvent,
  type MarkerLocationContext,
} from "@/lib/locationProvenance"
import type { EventRow } from "@/lib/types"

function event(payload: Record<string, unknown>, partial: Partial<EventRow> = {}): EventRow {
  return {
    id: "story",
    source: "rss-bbc-uk",
    source_event_id: "story",
    occurred_at: "2026-08-02T12:00:00Z",
    fetched_at: "2026-08-02T12:01:00Z",
    category: "news",
    severity: 0.2,
    keywords: [],
    country: "GB",
    lat: 51.5009,
    lon: -0.1774,
    payload,
    ...partial,
  }
}

describe("locationProvenanceForEvent", () => {
  it("uses the clicked exact-place marker instead of the row's primary place", () => {
    const marker: MarkerLocationContext = {
      name: "Wembley Stadium",
      wikidataId: "Q193633",
      description: "football stadium in London, England",
      lat: 51.556,
      lon: -0.2796,
      precision: "site",
      source: "wikidata",
      checkedAt: "2026-08-02T10:15:00+00:00",
      model: "place.wikidata.v1.3",
    }
    const result = locationProvenanceForEvent(
      event({
        place_name: "Royal Albert Hall",
        place_wikidata_id: "Q187868",
        geo_precision: "building",
        geo_source: "wikidata",
      }),
      marker,
    )

    expect(result).toMatchObject({
      precision: "exact-place",
      precisionDetail: "site",
      name: "Wembley Stadium",
      sourceLabel: "Wikidata",
      sourceId: "Q193633",
      sourceUrl: "https://www.wikidata.org/wiki/Q193633",
      checkedAt: "2026-08-02T10:15:00+00:00",
      model: "place.wikidata.v1.3",
      lat: 51.556,
      lon: -0.2796,
    })
  })

  it("states city precision and names Natural Earth without claiming verification", () => {
    const result = locationProvenanceForEvent(
      event({ city: "Manchester", geo_basis: "city" }),
    )

    expect(result).toMatchObject({
      precision: "city",
      name: "Manchester",
      sourceLabel: "Natural Earth gazetteer",
      sourceUrl: null,
      checkedAt: null,
      model: null,
    })
    expect(result.note).toContain("no street or building")
  })

  it("states region precision without upgrading it to a city", () => {
    const result = locationProvenanceForEvent(
      event({ region: "West Midlands", geo_basis: "region", geo_source: "natural-earth" }),
    )

    expect(result).toMatchObject({
      precision: "region",
      name: "West Midlands",
      sourceLabel: "Natural Earth gazetteer",
    })
    expect(result.note).toContain("no city or exact site")
  })

  it("shows missing provenance honestly", () => {
    const result = locationProvenanceForEvent(event({}))

    expect(result).toMatchObject({
      precision: "unknown",
      name: null,
      sourceLabel: "Not recorded",
      sourceUrl: null,
      sourceId: null,
      checkedAt: null,
    })
    expect(result.note).toBe("Coordinate precision is not recorded.")
  })

  it("never borrows primary evidence for a secondary marker", () => {
    const result = locationProvenanceForEvent(
      event({
        place_name: "Primary Hall",
        place_wikidata_id: "Q100",
        place_description: "description of the primary place",
        place_checked_at: "2026-08-02T10:00:00Z",
        place_model: "place.wikidata.v1.3",
        geo_precision: "building",
        geo_source: "wikidata",
      }),
      {
        lat: 1,
        lon: 2,
        name: "Secondary Hall",
        wikidataId: "Q200",
        precision: "site",
        source: "wikidata",
        description: null,
        checkedAt: null,
        model: null,
      },
    )

    expect(result).toMatchObject({
      name: "Secondary Hall",
      sourceId: "Q200",
      description: null,
      checkedAt: null,
      model: null,
    })
  })

  it("does not present one exact place for an ambiguous cluster selection", () => {
    const result = locationProvenanceForEvent(
      event({
        place_name: "Primary Hall",
        place_wikidata_id: "Q100",
        geo_precision: "building",
        geo_source: "wikidata",
      }),
      {
        name: "Multiple verified places",
        precision: "unknown",
        source: "multiple-marker-cluster",
      },
    )

    expect(result).toMatchObject({
      precision: "unknown",
      name: "Multiple verified places",
      sourceLabel: "Multiple marker locations",
      sourceId: null,
      lat: null,
      lon: null,
    })
    expect(result.note).toContain("Zoom in")
  })

  it("reads abuse.ch's recorded geolocation name", () => {
    const result = locationProvenanceForEvent(
      event(
        { geo_city: "Mountain View", geo_country: "US" },
        { source: "abuse-ch-urlhaus", category: "cyber" },
      ),
    )

    expect(result.name).toBe("Mountain View")
    expect(result.sourceLabel).toBe("abuse.ch geolocation")
  })

  it("labels known upstream coordinates without inventing their precision", () => {
    const result = locationProvenanceForEvent(
      event({ place: "10 km west of Tokyo" }, { source: "usgs-quake", category: "hazard" }),
    )

    expect(result.precision).toBe("unknown")
    expect(result.sourceLabel).toBe("USGS reported epicentre")
  })
})
