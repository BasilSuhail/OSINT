import { describe, expect, it } from "vitest"
import { hazardKind, hazardColor, hazardIcon, footprintFeatures } from "@/lib/hazardSymbols"
import type { EventRow } from "@/lib/types"

function row(p: Partial<EventRow>): EventRow {
  return {
    id: 1, source: "gdacs", source_event_id: "x", occurred_at: "2026-06-24T00:00:00Z",
    category: "hazard", severity: 0.5, confidence: null, keywords: [],
    country: "VE", lat: 10, lon: -67, payload: {}, ...p,
  } as EventRow
}

describe("hazardKind", () => {
  it("maps USGS to EQ", () => expect(hazardKind(row({ source: "usgs-quake" }))).toBe("EQ"))
  it("maps FIRMS to WF", () => expect(hazardKind(row({ source: "nasa-firms" }))).toBe("WF"))
  it("reads GDACS event_type", () => {
    expect(hazardKind(row({ payload: { event_type: "TC" } }))).toBe("TC")
    expect(hazardKind(row({ payload: { event_type: "FL" } }))).toBe("FL")
    expect(hazardKind(row({ payload: { event_type: "VO" } }))).toBe("VO")
    expect(hazardKind(row({ payload: { event_type: "DR" } }))).toBe("DR")
  })
  it("infers EONET kind from the title", () => {
    expect(hazardKind(row({ source: "eonet", payload: { title: "Typhoon Mekkhala" } }))).toBe("TC")
    expect(hazardKind(row({ source: "eonet", payload: { title: "Tropical Storm Higos" } }))).toBe("TC")
    expect(hazardKind(row({ source: "eonet", payload: { title: "Kilauea Volcano" } }))).toBe("VO")
  })
  it("promotes EONET ice and snow categories to first-class hazards", () => {
    expect(hazardKind(row({ source: "eonet", payload: { categories: ["seaLakeIce"], title: "Sea Ice" } }))).toBe("ICE")
    expect(hazardKind(row({ source: "eonet", payload: { categories: ["snow"], title: "Heavy Snow" } }))).toBe("ICE")
    expect(hazardIcon("ICE")).toBe("snowflake")
    expect(hazardColor(row({ source: "eonet", payload: { categories: ["seaLakeIce"] } }))).toBe("#67e8f9")
  })
  it("falls back to other", () => expect(hazardKind(row({ source: "gdelt", payload: {} }))).toBe("other"))
})

describe("hazardColor", () => {
  it("uses GDACS alert level", () => {
    expect(hazardColor(row({ payload: { alert_level: "Red" } }))).toBe("#ef4444")
    expect(hazardColor(row({ payload: { alert_level: "Orange" } }))).toBe("#f97316")
    expect(hazardColor(row({ payload: { alert_level: "Green" } }))).toBe("#22c55e")
  })
  it("colours USGS quakes by magnitude band", () => {
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 6.4 } }))).toBe("#ef4444")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 5.0 } }))).toBe("#f97316")
    expect(hazardColor(row({ source: "usgs-quake", payload: { magnitude: 3.0 } }))).toBe("#22c55e")
  })
  it("colours quakes consistently across sources (magnitude, not GDACS alert)", () => {
    // A GDACS quake uses magnitude too — so the same M5.0 quake reads orange
    // whether it came from USGS or GDACS, even if GDACS tagged it green alert.
    const usgs = hazardColor(row({ source: "usgs-quake", payload: { magnitude: 5.0 } }))
    const gdacs = hazardColor(
      row({ source: "gdacs", payload: { event_type: "EQ", magnitude: 5.0, alert_level: "Green" } }),
    )
    expect(gdacs).toBe(usgs)
    expect(gdacs).toBe("#f97316")
  })
})

describe("hazardIcon", () => {
  it("maps kind to a lucide key", () => {
    expect(hazardIcon("EQ")).toBe("activity")
    expect(hazardIcon("WF")).toBe("flame")
    expect(hazardIcon("other")).toBe("dot")
  })
  it("maps storm/flood/volcano icons", () => {
    expect(hazardIcon("TC")).toBe("wind")
    expect(hazardIcon("FL")).toBe("droplets")
    expect(hazardIcon("VO")).toBe("triangle")
  })
})

describe("footprintFeatures", () => {
  it("emits multiple ring features for a strong quake", () => {
    const f = footprintFeatures(row({ source: "usgs-quake", payload: { magnitude: 6.5, depth_km: 10 } }))
    expect(f.length).toBeGreaterThan(1)
    expect(f[0].geometry.type).toBe("Polygon")
    expect(f[0].properties?.color).toBeTypeOf("string")
  })
  it("emits one circle for a fire with a burned area", () => {
    const f = footprintFeatures(row({ payload: { event_type: "WF", severity_raw: "... in 8028 ha", alert_level: "Green" } }))
    expect(f).toHaveLength(1)
    expect(f[0].properties?.color).toBeTypeOf("string")
    expect(f[0].properties?.fillOpacity).toBeTypeOf("number")
  })
  it("emits a burn circle for an EONET wildfire, which reports acres not ha text", () => {
    // EONET fires are a single Point, so the backend can never build geometry
    // for them; before #612 they drew nothing at all — a pin with no extent.
    const f = footprintFeatures(
      row({
        source: "eonet",
        payload: {
          title: "Wildfire CHELAN HILLS, Douglas, Washington",
          categories: ["wildfires"],
          magnitude_value: 9735,
          magnitude_unit: "acres",
        },
      }),
    )
    expect(f).toHaveLength(1)
    expect(f[0].geometry.type).toBe("Polygon")
  })
  it("sizes EONET sea ice from its square-nautical-mile extent", () => {
    const f = footprintFeatures(
      row({
        source: "eonet",
        severity: 0.2,
        payload: {
          title: "Iceberg A-84",
          categories: ["seaLakeIce"],
          magnitude_value: 725,
          magnitude_unit: "NM^2",
        },
      }),
    )
    expect(f).toHaveLength(1)
    // 725 NM^2 ≈ 2486 km² → ~28 km radius, far past the 20 km severity default.
    const ring = (f[0].geometry.coordinates as [number, number][][])[0]
    const lons = ring.map((c) => c[0])
    const spanKm = (Math.max(...lons) - Math.min(...lons)) * 111.32 * Math.cos((10 * Math.PI) / 180)
    expect(spanKm).toBeGreaterThan(50)
  })
  it("still draws nothing for a fire with no reported area", () => {
    const f = footprintFeatures(row({ source: "eonet", payload: { title: "Wildfire Unknown" } }))
    expect(f).toEqual([])
  })
  it("emits a wind-extent circle for a storm with no real geometry", () => {
    const f = footprintFeatures(row({ payload: { event_type: "TC", alert_level: "Orange" }, severity: 0.7 }))
    expect(f).toHaveLength(1)
    expect(f[0].geometry.type).toBe("Polygon")
  })
  it("emits the track line plus a wind circle for a cyclone with real geometry", () => {
    const f = footprintFeatures(
      row({
        source: "gdacs",
        payload: {
          event_type: "TC",
          alert_level: "Green",
          footprint_geojson: {
            type: "FeatureCollection",
            features: [
              { geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties: { color: "#22c55e", fillOpacity: 0.25 } },
              { geometry: { type: "LineString", coordinates: [[0, 0], [1, 1], [2, 2]] }, properties: { color: "#22c55e", fillOpacity: 0 } },
            ],
          },
        },
      }),
    )
    // real track line (LineString) + synthesized wind circle (Polygon)
    expect(f).toHaveLength(2)
    const types = f.map((x) => x.geometry.type)
    expect(types).toContain("LineString")
    expect(types).toContain("Polygon")
  })
  it("uses a modest wind circle for collapsed cyclone tracks instead of real cones", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        { geometry: { type: "Polygon", coordinates: [[[0, 0], [3, 0], [3, 3], [0, 0]]] }, properties: { color: "#22c55e", fillOpacity: 0.25 } },
        { geometry: { type: "LineString", coordinates: [[0, 0], [1, 1], [2, 2]] }, properties: { color: "#22c55e", fillOpacity: 0 } },
      ],
    }
    const f = footprintFeatures(
      row({
        source: "gdacs",
        lat: 10,
        lon: 20,
        payload: { event_type: "TC", magnitude: 40, alert_level: "Green", footprint_geojson: fc },
      }),
    )

    expect(f).toHaveLength(2)
    expect(f.map((x) => x.geometry.type)).toEqual(["LineString", "Polygon"])
    const windCircle = f.find((x) => x.geometry.type === "Polygon")
    expect(windCircle?.properties.fillOpacity).toBe(0.12)
  })
  it("expanded cyclone shows real cones + track, NOT a synthesized circle on top", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        { geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties: { color: "#22c55e", fillOpacity: 0.25 } },
        { geometry: { type: "LineString", coordinates: [[0, 0], [1, 1], [2, 2]] }, properties: { color: "#22c55e", fillOpacity: 0 } },
      ],
    }
    const f = footprintFeatures(
      row({ source: "gdacs", payload: { event_type: "TC", alert_level: "Green", footprint_geojson: fc } }),
      true, // expanded / clicked
    )
    expect(f).toHaveLength(2) // real polygon + line only — no extra synthesized circle
    expect(f.filter((x) => x.geometry.type === "Polygon")).toHaveLength(1)
    expect(f.filter((x) => x.geometry.type === "LineString")).toHaveLength(1)
  })
  it("emits nothing when there is no usable geometry", () => {
    expect(footprintFeatures(row({ source: "gdelt", payload: {}, lat: null, lon: null }))).toHaveLength(0)
  })
  it("passes real upstream geometry through when payload has footprint_geojson", () => {
    const f = footprintFeatures(
      row({
        source: "gdacs",
        payload: {
          event_type: "WF",
          alert_level: "Red",
          footprint_geojson: {
            type: "FeatureCollection",
            features: [
              {
                geometry: { type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
                properties: { color: "#ef4444", fillOpacity: 0.25 },
              },
            ],
          },
        },
      }),
    )
    expect(f).toHaveLength(1)
    expect(f[0].geometry.type).toBe("MultiPolygon")
    expect(f[0].properties.color).toBe("#ef4444")
  })
  it("prefers real geometry over the synthesized circle even with coords present", () => {
    const f = footprintFeatures(
      row({
        source: "usgs-quake",
        lat: 10,
        lon: 20,
        payload: {
          magnitude: 6.5,
          footprint_geojson: {
            type: "FeatureCollection",
            features: [
              { geometry: { type: "MultiLineString", coordinates: [[[0, 0], [1, 1]]] }, properties: { color: "#90f2ff", fillOpacity: 0 } },
            ],
          },
        },
      }),
    )
    expect(f).toHaveLength(1)
    expect(f[0].geometry.type).toBe("MultiLineString")
  })
})
