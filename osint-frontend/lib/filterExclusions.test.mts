import { describe, expect, it } from "vitest"
import {
  activeExclusions,
  filtersHideEverything,
  severityIsNarrowed,
  type FilterSnapshot,
} from "./filterExclusions"

function filters(over: Partial<FilterSnapshot> = {}): FilterSnapshot {
  return {
    sources: { NEWS: true, GDELT: true, CYBER: true },
    hazardTypes: { EQ: true, TC: true, FL: true },
    severity: [0, 1],
    countries: [],
    keyword: "",
    ...over,
  }
}

describe("activeExclusions", () => {
  it("says nothing when nothing is excluded", () => {
    expect(activeExclusions(filters())).toEqual([])
  })

  it("counts the layers and disaster types that are off", () => {
    const out = activeExclusions(
      filters({
        sources: { NEWS: true, GDELT: false, CYBER: false },
        hazardTypes: { EQ: true, TC: false, FL: true },
      }),
    )
    expect(out).toEqual(["2 layers off", "1 disaster type off"])
  })

  it("names a narrowed severity range, which is the one that empties the map quietly", () => {
    expect(activeExclusions(filters({ severity: [0.34, 1] }))).toEqual(["severity 0.34–1.00"])
    expect(activeExclusions(filters({ severity: [0, 0.5] }))).toEqual(["severity 0.00–0.50"])
  })

  it("names countries and a keyword", () => {
    expect(activeExclusions(filters({ countries: ["UA"] }))).toEqual(["1 country"])
    expect(activeExclusions(filters({ countries: ["UA", "IL"] }))).toEqual(["2 countries"])
    expect(activeExclusions(filters({ keyword: "  quake " }))).toEqual(["keyword “quake”"])
  })

  it("lists every excluding filter, rail order", () => {
    expect(
      activeExclusions(
        filters({
          sources: { NEWS: false, GDELT: true, CYBER: true },
          severity: [0.2, 0.9],
          countries: ["UA"],
          keyword: "flood",
        }),
      ),
    ).toEqual(["1 layer off", "severity 0.20–0.90", "1 country", "keyword “flood”"])
  })
})

describe("severityIsNarrowed", () => {
  it("is false only for the full range", () => {
    expect(severityIsNarrowed([0, 1])).toBe(false)
    expect(severityIsNarrowed([0.01, 1])).toBe(true)
    expect(severityIsNarrowed([0, 0.99])).toBe(true)
  })
})

describe("filtersHideEverything", () => {
  it("fires when the window has events and none survive the filters", () => {
    expect(filtersHideEverything(0, 7500)).toBe(true)
  })

  it("stays quiet when there is simply nothing in the window", () => {
    expect(filtersHideEverything(0, 0)).toBe(false)
  })

  it("stays quiet while anything is visible", () => {
    expect(filtersHideEverything(1, 7500)).toBe(false)
  })
})
