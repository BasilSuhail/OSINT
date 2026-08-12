/**
 * How the city and weather blocks read (#932).
 *
 * Every one of these is a number the screen must not overstate: a distance the
 * reader uses to judge whether the weather is about their point, a window the
 * high and low actually cover, and a wind direction that means the opposite of
 * what a naive reading gives.
 */
import { describe, expect, it } from "vitest"

import { compass, distanceLabel, rangeLabel, temperature, windLabel } from "./placeFormat"

describe("distanceLabel", () => {
  it("says the point is in the place when it is", () => {
    expect(distanceLabel(0)).toBe("here")
    expect(distanceLabel(0.4)).toBe("here")
  })

  it("gives hundreds of metres their own reading", () => {
    expect(distanceLabel(0.8)).toBe("800 m away")
  })

  it("rounds kilometres to something a reader can hold", () => {
    expect(distanceLabel(4.32)).toBe("4.3 km away")
    expect(distanceLabel(41.7)).toBe("42 km away")
  })
})

describe("temperature", () => {
  it("shows one decimal, because weather is not measured finer", () => {
    expect(temperature(21.44)).toBe("21.4°C")
  })

  it("keeps the minus sign visible", () => {
    expect(temperature(-3.24)).toBe("-3.2°C")
  })

  it("has nothing to say about a missing reading", () => {
    expect(temperature(null)).toBeNull()
  })
})

describe("compass", () => {
  it("reads the direction the wind comes FROM, as meteorology means it", () => {
    expect(compass(0)).toBe("N")
    expect(compass(90)).toBe("E")
    expect(compass(180)).toBe("S")
    expect(compass(270)).toBe("W")
  })

  it("rounds to the nearest of sixteen points", () => {
    expect(compass(23)).toBe("NNE")
    expect(compass(359)).toBe("N")
  })
})

describe("windLabel", () => {
  it("puts the speed in the unit a person uses, with the direction", () => {
    // 5 m/s is 18 km/h.
    expect(windLabel(5, 200)).toBe("18 km/h from SSW")
  })

  it("drops the direction when there is none", () => {
    expect(windLabel(5, null)).toBe("18 km/h")
  })

  it("has nothing to say about a missing reading", () => {
    expect(windLabel(null, 200)).toBeNull()
  })
})

describe("rangeLabel", () => {
  it("names the window the numbers actually cover", () => {
    expect(rangeLabel(24)).toBe("next 24 h")
    expect(rangeLabel(6)).toBe("next 6 h")
  })

  it("says nothing rather than claim a window of no hours", () => {
    expect(rangeLabel(0)).toBeNull()
  })
})
