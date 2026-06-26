import { describe, expect, it } from "vitest"
import {
  circlePolygon,
  feltRadiusKm,
  parseBurnedHa,
  fireRadiusKm,
  quakeBands,
} from "@/lib/footprints"

describe("circlePolygon", () => {
  it("returns a closed ring with steps+1 points", () => {
    const ring = circlePolygon(0, 0, 100, 32)
    expect(ring).toHaveLength(33)
    expect(ring[0]).toEqual(ring[ring.length - 1])
  })

  it("offsets roughly radius/111km in degrees at the equator", () => {
    const ring = circlePolygon(0, 0, 111, 4)
    const lons = ring.map((p) => p[0])
    expect(Math.max(...lons)).toBeCloseTo(1, 1) // ~1 degree east
  })
})

describe("feltRadiusKm", () => {
  it("grows with magnitude", () => {
    expect(feltRadiusKm(7, 10, 4)).toBeGreaterThan(feltRadiusKm(5, 10, 4))
  })
  it("shrinks as the target intensity rises", () => {
    expect(feltRadiusKm(6.5, 10, 7)).toBeLessThan(feltRadiusKm(6.5, 10, 4))
  })
  it("shrinks with depth (surface projection)", () => {
    expect(feltRadiusKm(6.5, 100, 5)).toBeLessThan(feltRadiusKm(6.5, 10, 5))
  })
  it("returns 0 when the band intensity exceeds the epicentre", () => {
    expect(feltRadiusKm(3, 10, 9)).toBe(0)
  })
})

describe("parseBurnedHa", () => {
  it("pulls hectares out of GDACS severity text", () => {
    expect(parseBurnedHa("Green impact for forestfire in 8028 ha")).toBe(8028)
  })
  it("handles thousands separators", () => {
    expect(parseBurnedHa("... in 12,500 ha")).toBe(12500)
  })
  it("returns null when no ha present", () => {
    expect(parseBurnedHa("Orange alert")).toBeNull()
    expect(parseBurnedHa(null)).toBeNull()
  })
})

describe("fireRadiusKm", () => {
  it("derives radius from area (8028 ha ≈ 5 km)", () => {
    expect(fireRadiusKm(8028)).toBeCloseTo(5.05, 1)
  })
})

describe("quakeBands", () => {
  it("returns only bands with a positive radius, strongest last", () => {
    const bands = quakeBands(6.5, 10)
    expect(bands.length).toBeGreaterThan(0)
    for (const b of bands) expect(b.radiusKm).toBeGreaterThan(0)
    // radii strictly decrease as mmi rises
    const radii = bands.map((b) => b.radiusKm)
    const sorted = [...radii].sort((a, z) => z - a)
    expect(radii).toEqual(sorted)
  })
})
