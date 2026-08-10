import { describe, expect, it } from "vitest"
import {
  FOCUS_DIM,
  ambientFootprints,
  focusLayerOpacity,
  focusOpacity,
  focusable,
} from "@/lib/mapFocus"
import type { HazardFootprintCollection } from "@/lib/mapFootprints"

const ambient: HazardFootprintCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { color: "#f00", fillOpacity: 0.2, selected: false },
      geometry: { type: "Point", coordinates: [0, 0] },
    },
  ],
}

describe("focusable", () => {
  it("isolates hazards and weather", () => {
    expect(focusable({ category: "hazard" })).toBe(true)
    expect(focusable({ category: "weather" })).toBe(true)
  })

  it("leaves the map alone for rows that draw no footprint", () => {
    expect(focusable({ category: "news" })).toBe(false)
  })
})

describe("ambientFootprints", () => {
  it("keeps every footprint when nothing holds focus", () => {
    expect(ambientFootprints(ambient, false)).toBe(ambient)
  })

  it("drops the other hazards' geometry while one holds focus", () => {
    expect(ambientFootprints(ambient, true).features).toHaveLength(0)
  })
})

describe("focusOpacity", () => {
  it("leaves the focused hazard at whatever age gave it", () => {
    expect(focusOpacity(0.6, true, true)).toBe(0.6)
  })

  it("fades the neighbours without hiding them", () => {
    const dimmed = focusOpacity(1, true, false)
    expect(dimmed).toBe(FOCUS_DIM)
    expect(dimmed).toBeGreaterThan(0)
  })

  it("changes nothing when focus is off", () => {
    expect(focusOpacity(1, false, false)).toBe(1)
  })
})

describe("focusLayerOpacity", () => {
  it("is a no-op multiplier until focus is on", () => {
    expect(focusLayerOpacity(false)).toBe(1)
    expect(focusLayerOpacity(true)).toBe(FOCUS_DIM)
  })
})
