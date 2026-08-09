import { describe, expect, it } from "vitest"
import { IMAGERY_LAYERS, imageryDate, imageryLayer, imageryTiles } from "../lib/imageryLayers"

describe("imageryDate", () => {
  it("is the UTC day the timestamp falls in", () => {
    expect(imageryDate(Date.UTC(2026, 7, 1, 12, 0, 0))).toBe("2026-08-01")
  })

  it("does not roll forward late in the UTC day", () => {
    expect(imageryDate(Date.UTC(2026, 7, 1, 23, 59, 59))).toBe("2026-08-01")
  })

  it("rolls at midnight UTC, not at local midnight", () => {
    expect(imageryDate(Date.UTC(2026, 7, 2, 0, 0, 0))).toBe("2026-08-02")
  })
})

describe("imageryTiles", () => {
  it("addresses tiles row before column, as the publisher does", () => {
    // Verified against the live endpoint: at z=6 the London tile is x=31,
    // y=21, and requesting it as z/y/x returns southern England. The other
    // order also returns a valid image — of somewhere else entirely — so
    // getting this backwards ships a basemap silently offset from the map.
    const [template] = imageryTiles("truecolour", "2026-08-01")!
    expect(template.endsWith("/{z}/{y}/{x}.jpg")).toBe(true)
  })

  it("puts the requested day in the path", () => {
    const [template] = imageryTiles("nightlights", "2026-08-01")!
    expect(template).toContain("/default/2026-08-01/")
  })

  it("uses each product's own published depth", () => {
    expect(imageryTiles("nightlights", "2026-08-01")![0]).toContain("Level8")
    expect(imageryTiles("truecolour", "2026-08-01")![0]).toContain("Level9")
  })

  it("has nothing to draw for a layer that does not exist", () => {
    expect(imageryTiles("nope", "2026-08-01")).toBeNull()
    expect(imageryLayer("nope")).toBeNull()
  })
})

describe("the layer registry", () => {
  it("stays small enough to read", () => {
    // Every toggle is a decision the operator has to make. Three useful layers
    // beat ten that need explaining.
    expect(IMAGERY_LAYERS.length).toBeLessThanOrEqual(3)
  })

  it("gives every layer a hint, because none of them explain themselves", () => {
    for (const layer of IMAGERY_LAYERS) {
      expect(layer.hint.length).toBeGreaterThan(0)
      expect(layer.opacity).toBeGreaterThan(0)
      expect(layer.opacity).toBeLessThanOrEqual(1)
    }
  })

  it("has no duplicate ids", () => {
    const ids = IMAGERY_LAYERS.map((l) => l.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
