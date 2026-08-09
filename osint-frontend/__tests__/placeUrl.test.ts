import { describe, expect, it } from "vitest"
import { placeUrl } from "../lib/placeUrl"

const BASE = "http://api.invalid"

describe("placeUrl", () => {
  it("asks about the point that was right-clicked", () => {
    expect(placeUrl({ lat: 57.14, lon: -2.09 }, BASE)).toBe(
      "http://api.invalid/geo/place?lat=57.14&lon=-2.09",
    )
  })

  it("asks about a country when there is no point", () => {
    expect(placeUrl({ iso: "FR" }, BASE)).toBe("http://api.invalid/geo/place?iso=FR")
  })

  it("prefers the point when it has both", () => {
    expect(placeUrl({ lat: 0, lon: 0, iso: "FR" }, BASE)).toBe(
      "http://api.invalid/geo/place?lat=0&lon=0",
    )
  })

  it("keeps the null island askable", () => {
    // Zero is a coordinate, not a missing value. A truthiness check here would
    // silently drop the one point on Earth whose numbers are both zero.
    expect(placeUrl({ lat: 0, lon: 0 }, BASE)).not.toBeNull()
  })

  it("has nothing to ask when the target is empty", () => {
    expect(placeUrl({}, BASE)).toBeNull()
  })

  it("has nothing to ask with half a point", () => {
    expect(placeUrl({ lat: 57.14 }, BASE)).toBeNull()
  })
})
