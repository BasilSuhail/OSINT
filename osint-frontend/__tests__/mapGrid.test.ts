import { describe, expect, it } from "vitest"
import {
  GRID_EXCLUDE_SOURCES,
  abbreviateCount,
  cellDegForZoom,
  gridBoundsFor,
  gridCellsToFeatures,
  type GridCell,
} from "@/lib/mapGrid"

function cell(over: Partial<GridCell> = {}): GridCell {
  return { lat: 10, lon: 20, cell_deg: 2, category: "news", count: 5, max_severity: 0.4, ...over }
}

describe("gridCellsToFeatures", () => {
  it("sums the categories that share a cell", () => {
    const fc = gridCellsToFeatures([
      cell({ category: "news", count: 5 }),
      cell({ category: "geopolitical", count: 7 }),
    ])
    expect(fc.features).toHaveLength(1)
    expect(fc.features[0].properties.point_count).toBe(12)
  })

  it("places the bubble at the centre of the cell it counts", () => {
    const fc = gridCellsToFeatures([cell({ lat: 10, lon: 20, cell_deg: 2 })])
    expect(fc.features[0].geometry.coordinates).toEqual([21, 11])
  })

  it("leaves hazards out, because each is already its own marker", () => {
    const fc = gridCellsToFeatures([
      cell({ category: "hazard", count: 99 }),
      cell({ category: "news", count: 3 }),
    ])
    expect(fc.features[0].properties.point_count).toBe(3)
  })

  it("drops a cell that is only hazards rather than drawing an empty bubble", () => {
    expect(gridCellsToFeatures([cell({ category: "hazard" })]).features).toHaveLength(0)
  })

  it("keeps the worst severity in the cell", () => {
    const fc = gridCellsToFeatures([
      cell({ category: "news", max_severity: 0.2 }),
      cell({ category: "geopolitical", max_severity: 0.9 }),
    ])
    expect(fc.features[0].properties.max_severity).toBe(0.9)
  })

  it("survives a cell with no severity at all", () => {
    const fc = gridCellsToFeatures([cell({ max_severity: null })])
    expect(fc.features[0].properties.max_severity).toBeNull()
  })

  it("separates cells that do not share a corner", () => {
    const fc = gridCellsToFeatures([cell({ lat: 10 }), cell({ lat: 40 })])
    expect(fc.features).toHaveLength(2)
  })
})

describe("abbreviateCount", () => {
  it("reads like a cluster count at every size", () => {
    expect(abbreviateCount(7)).toBe("7")
    expect(abbreviateCount(999)).toBe("999")
    expect(abbreviateCount(1_200)).toBe("1.2k")
    expect(abbreviateCount(43_748)).toBe("44k")
  })
})

describe("cellDegForZoom", () => {
  it("coarsens as the map zooms out", () => {
    expect(cellDegForZoom(0)).toBeGreaterThan(cellDegForZoom(2))
    expect(cellDegForZoom(2)).toBeGreaterThanOrEqual(cellDegForZoom(7))
  })

  it("never asks for a world grid finer than the measured one", () => {
    for (const zoom of [-5, 0, 3, 8, 22]) {
      expect(cellDegForZoom(zoom)).toBeGreaterThanOrEqual(2)
      expect(cellDegForZoom(zoom)).toBeLessThanOrEqual(8)
    }
  })
})

/** Bounds are normalised to ±180, so a world view arrives with west greater
 *  than east — indistinguishable from an antimeridian pan, and read as one it
 *  selects the two Pacific edges and excludes everything between. That is what
 *  emptied the map of news while leaving a few bubbles on its borders. */
describe("gridBoundsFor", () => {
  it("asks for the world rather than a strip when the box wraps", () => {
    expect(gridBoundsFor({ west: 110, south: -90, east: -110, north: 90 })).toBeNull()
  })

  it("passes an ordinary box straight through", () => {
    const box = { west: -10, south: 40, east: 20, north: 60 }
    expect(gridBoundsFor(box)).toEqual(box)
  })

  it("asks for the world when the map has not reported bounds yet", () => {
    expect(gridBoundsFor(null)).toBeNull()
  })
})

/** A cell stands in for the cluster layer, which only ever held clusterable
 *  rows. Anything drawn as its own marker would otherwise be on the map twice,
 *  and the two feeds nothing draws would be most of every count. */
describe("GRID_EXCLUDE_SOURCES", () => {
  it("leaves out the feeds the map never draws", () => {
    expect(GRID_EXCLUDE_SOURCES).toContain("opensky-adsb")
    expect(GRID_EXCLUDE_SOURCES).toContain("nasa-firms")
  })

  it("leaves out every source drawn as its own marker", () => {
    for (const source of ["gdacs", "usgs-quake", "eonet", "abuse-ch-urlhaus", "fred"]) {
      expect(GRID_EXCLUDE_SOURCES).toContain(source)
    }
  })

  it("keeps the sources the cluster layer actually held", () => {
    for (const source of ["gdelt", "uk-police", "rss-bbc-world"]) {
      expect(GRID_EXCLUDE_SOURCES).not.toContain(source)
    }
  })
})
