import { describe, expect, it } from "vitest"
import {
  coordinateLabel,
  distanceKm,
  localEventSelections,
  localMapLabel,
  localSelectionBounds,
  localSelectionRadiusKm,
} from "@/lib/localMapSelection"

describe("localMapLabel", () => {
  it("prefers a clicked street over the city behind it", () => {
    expect(
      localMapLabel([
        { layer: { id: "place_city" }, properties: { name: "Edinburgh" } },
        { layer: { id: "highway_name_other" }, properties: { name: "Princes Street" } },
      ]),
    ).toEqual({ name: "Princes Street", kind: "street" })
  })

  it("uses neighbourhood labels for local selection", () => {
    expect(
      localMapLabel([
        { layer: { id: "place_suburb" }, properties: { name_en: "Brooklyn" } },
      ]),
    ).toEqual({ name: "Brooklyn", kind: "neighbourhood" })
  })

  it("uses a named building before the street beneath it", () => {
    expect(
      localMapLabel([
        { layer: { id: "highway_name_other" }, properties: { name: "Lothian Road" } },
        { layer: { id: "building" }, properties: { name: "Usher Hall" } },
      ]),
    ).toEqual({ name: "Usher Hall", kind: "place" })
  })

  it("never turns a country label into a local selection", () => {
    expect(
      localMapLabel([
        { layer: { id: "place_country_major" }, properties: { name: "United Kingdom" } },
        { layer: { id: "country-fill" }, properties: { __iso: "GB" } },
      ]),
    ).toBeNull()
  })
})

describe("localSelectionRadiusKm", () => {
  it("scales from city to street while remaining bounded", () => {
    expect(localSelectionRadiusKm(1)).toBe(50)
    expect(localSelectionRadiusKm(8)).toBe(50)
    expect(localSelectionRadiusKm(12)).toBe(3.1)
    expect(localSelectionRadiusKm(16)).toBe(0.2)
    expect(localSelectionRadiusKm(22)).toBe(0.15)
  })

  it("keeps named ground selections local at broad zoom", () => {
    expect(localSelectionRadiusKm(8, "city")).toBe(15)
    expect(localSelectionRadiusKm(8, "neighbourhood")).toBe(5)
    expect(localSelectionRadiusKm(8, "street")).toBe(0.75)
    expect(localSelectionRadiusKm(8, "place")).toBe(0.5)
  })
})

describe("localEventSelections", () => {
  const event = (id: string, occurredAt: string) => ({ id, occurred_at: occurredAt })

  it("keeps only events inside the selected ground radius", () => {
    const selections = localEventSelections(
      [
        { ev: event("near", "2026-08-03T12:00:00Z"), lat: 55.953, lon: -3.19 },
        { ev: event("far", "2026-08-03T12:00:00Z"), lat: 56.5, lon: -3.19 },
      ],
      55.953,
      -3.19,
      5,
    )
    expect(selections.map((selection) => selection.event.id)).toEqual(["near"])
  })

  it("deduplicates a multi-place story using its nearest verified point", () => {
    const shared = event("story", "2026-08-03T12:00:00Z")
    const selections = localEventSelections(
      [
        { ev: shared, lat: 55.96, lon: -3.2, location: "farther" },
        { ev: shared, lat: 55.9531, lon: -3.1901, location: "nearest" },
      ],
      55.953,
      -3.19,
      5,
    )
    expect(selections).toHaveLength(1)
    expect(selections[0]?.location).toBe("nearest")
  })

  it("orders by distance and then recency", () => {
    const selections = localEventSelections(
      [
        { ev: event("farther", "2026-08-03T13:00:00Z"), lat: 55.96, lon: -3.19 },
        { ev: event("older", "2026-08-03T11:00:00Z"), lat: 55.953, lon: -3.19 },
        { ev: event("newer", "2026-08-03T12:00:00Z"), lat: 55.953, lon: -3.19 },
      ],
      55.953,
      -3.19,
      5,
    )
    expect(selections.map((selection) => selection.event.id)).toEqual([
      "newer",
      "older",
      "farther",
    ])
  })
})

describe("map coordinate helpers", () => {
  it("formats stable fallback coordinates", () => {
    expect(coordinateLabel(55.953251, -3.188267)).toBe("55.95325, -3.18827")
  })

  it("computes a realistic short ground distance", () => {
    expect(distanceKm(55.953, -3.19, 55.954, -3.19)).toBeCloseTo(0.111, 2)
  })

  it("encloses a local radius in a queryable bounding box", () => {
    const bounds = localSelectionBounds(55.953, -3.19, 5)
    expect(bounds.south).toBeLessThan(55.953)
    expect(bounds.north).toBeGreaterThan(55.953)
    expect(bounds.west).toBeLessThan(-3.19)
    expect(bounds.east).toBeGreaterThan(-3.19)
  })

  it("represents antimeridian wrap with west greater than east", () => {
    const bounds = localSelectionBounds(0, 179.9, 50)
    expect(bounds.west).toBeGreaterThan(bounds.east)
  })
})
