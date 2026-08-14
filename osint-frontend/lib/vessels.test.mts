import { describe, expect, it } from "vitest"
import {
  suspectReason,
  vesselAttribution,
  vesselBearing,
  vesselFacts,
  vesselIsUnderWay,
  vesselTitle,
  type PresenceVessel,
} from "./vessels"

const vessel = (over: Partial<PresenceVessel> = {}): PresenceVessel => ({
  mmsi: 230941570,
  name: "MERIKUOKKA",
  callsign: "OI2932",
  imo: 9123456,
  lat: 59.36,
  lon: 18.44,
  speed_kt: 11.4,
  course: 18.9,
  heading: 14,
  nav_status: "under way",
  category: "cargo",
  ship_type: 70,
  destination: "RAUMA",
  position_accurate: true,
  position_suspect: null,
  reported_at: "2026-08-13T21:03:02+00:00",
  ...over,
})

describe("naming a vessel", () => {
  it("falls back the way AIS degrades", () => {
    expect(vesselTitle(vessel())).toBe("MERIKUOKKA")
    expect(vesselTitle(vessel({ name: null }))).toBe("OI2932")
    expect(vesselTitle(vessel({ name: null, callsign: null }))).toBe("MMSI 230941570")
    expect(vesselTitle(vessel({ name: null, callsign: null, mmsi: null }))).toBe(
      "Unknown vessel",
    )
  })
})

describe("which way a hull points", () => {
  //: Heading is what the hull is pointing at; course is where it is going.
  //: They differ in a current, and the hull is what is being drawn.
  it("prefers the heading over the course", () => {
    expect(vesselBearing(vessel())).toBe(14)
  })

  it("falls back to the course when no heading was sent", () => {
    expect(vesselBearing(vessel({ heading: null }))).toBe(18.9)
  })

  it("points nowhere when neither was sent", () => {
    expect(vesselBearing(vessel({ heading: null, course: null }))).toBeNull()
  })
})

describe("whether a vessel is going anywhere", () => {
  it("reads speed as movement", () => {
    expect(vesselIsUnderWay(vessel())).toBe(true)
  })

  //: Below half a knot is a moored ship's own position wandering, not travel.
  it("does not call a drifting fix movement", () => {
    expect(vesselIsUnderWay(vessel({ speed_kt: 0.2, nav_status: null }))).toBe(false)
  })

  //: A ship at anchor swings on its cable and reports a speed while doing it.
  //: What it says it is doing outranks what its speed implies.
  it("believes at anchor and moored over the speed", () => {
    expect(vesselIsUnderWay(vessel({ nav_status: "at anchor", speed_kt: 1.2 }))).toBe(false)
    expect(vesselIsUnderWay(vessel({ nav_status: "moored", speed_kt: 0.9 }))).toBe(false)
  })
})

describe("what the card says", () => {
  it("labels the destination as a claim, not a fact", () => {
    expect(vesselFacts(vessel())).toContainEqual({
      label: "says bound for",
      value: "RAUMA",
    })
  })

  it("says stopped rather than nought knots", () => {
    expect(vesselFacts(vessel({ speed_kt: 0 }))).toContainEqual({
      label: "speed",
      value: "stopped",
    })
  })

  //: A vessel that transmitted no type is not filed under one.
  it("leaves out a type that was never transmitted", () => {
    const facts = vesselFacts(vessel({ category: "other", ship_type: null }))
    expect(facts.map((f) => f.label)).not.toContain("type")
  })

  it("leaves out every field the vessel never sent", () => {
    const facts = vesselFacts(
      vessel({ destination: null, callsign: null, imo: null, nav_status: null }),
    )
    const labels = facts.map((f) => f.label)
    expect(labels).not.toContain("says bound for")
    expect(labels).not.toContain("call sign")
    expect(labels).not.toContain("IMO")
    expect(labels).not.toContain("status")
  })
})

describe("a position the console does not believe", () => {
  it("says which test the position failed", () => {
    expect(suspectReason(vessel({ position_suspect: "speed" }))).toBe(
      "reported speed no vessel can reach",
    )
    expect(suspectReason(vessel({ position_suspect: "stacked" }))).toBe(
      "several moving vessels on one position",
    )
  })

  //: Silence is the answer for ordinary traffic. A layer that hedges about
  //: every mark has said nothing about any of them.
  it("says nothing about a position it has no quarrel with", () => {
    expect(suspectReason(vessel())).toBeNull()
  })
})

describe("crediting whoever answered", () => {
  it("names every feed that reported", () => {
    expect(vesselAttribution(["Fintraffic · CC BY 4.0", "BarentsWatch · NLOD"])).toBe(
      "Fintraffic · CC BY 4.0 · BarentsWatch · NLOD",
    )
  })

  //: Falling back to a guess would print a licence notice for a feed that did
  //: not answer, which is worse than printing none.
  it("invents nothing when nothing said who it was", () => {
    expect(vesselAttribution([])).toBeNull()
    expect(vesselAttribution(undefined)).toBeNull()
    expect(vesselAttribution(["  "])).toBeNull()
  })
})

