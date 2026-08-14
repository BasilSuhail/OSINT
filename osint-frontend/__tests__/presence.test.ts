import { describe, expect, it } from "vitest"
import {
  aircraftFacts,
  aircraftTitle,
  ageLabel,
  shouldPoll,
  windowIsNow,
  type PresenceAircraft,
} from "../lib/presence"

describe("when presence may be shown", () => {
  it("is shown at now", () => {
    expect(windowIsNow(0)).toBe(true)
  })

  it("is hidden once the scrubber leaves now", () => {
    // Nothing is stored, so there is no past to draw. Leaving live dots over a
    // three-week-old map would make them look like history.
    expect(windowIsNow(3 * 24 * 60 * 60 * 1000)).toBe(false)
  })

  it("tolerates the small offset a live window naturally carries", () => {
    expect(windowIsNow(60_000)).toBe(true)
  })
})

describe("when to ask", () => {
  it("asks only when switched on, visible, and at now", () => {
    expect(shouldPoll(true, 0, true)).toBe(true)
  })

  it("does not ask while the layer is off", () => {
    expect(shouldPoll(false, 0, true)).toBe(false)
  })

  it("does not ask from a background tab", () => {
    // A free community service should not pay for a tab nobody is looking at.
    expect(shouldPoll(true, 0, false)).toBe(false)
  })

  it("does not ask while scrubbed into the past", () => {
    expect(shouldPoll(true, 86_400_000, true)).toBe(false)
  })
})

describe("ageLabel", () => {
  it("counts seconds while it is seconds", () => {
    expect(ageLabel("2026-08-09T12:00:00+00:00", Date.parse("2026-08-09T12:00:08Z"))).toBe(
      "as of 8s ago",
    )
  })

  it("switches to minutes once it matters", () => {
    expect(ageLabel("2026-08-09T12:00:00+00:00", Date.parse("2026-08-09T12:03:00Z"))).toBe(
      "as of 3m ago",
    )
  })

  it("never reports the future", () => {
    expect(ageLabel("2026-08-09T12:00:10+00:00", Date.parse("2026-08-09T12:00:00Z"))).toBe(
      "as of 0s ago",
    )
  })
})

describe("what a clicked aircraft says", () => {
  const plane = (over: Partial<PresenceAircraft> = {}): PresenceAircraft => ({
    hex: "43c6e2",
    callsign: "RRR2317",
    type: "A400",
    registration: "ZM413",
    lat: 51.1,
    lon: -1.2,
    track: 128.4,
    alt_ft: 24_000,
    speed_kt: 451.2,
    squawk: "6154",
    kind: "military",
    role: "transport",
    watch: null,
    airborne_since: null,
    ...over,
  })

  it("titles a plane by the name a listener would hear first", () => {
    expect(aircraftTitle(plane())).toBe("RRR2317")
    expect(aircraftTitle(plane({ callsign: null }))).toBe("ZM413")
    expect(aircraftTitle(plane({ callsign: null, registration: null }))).toBe("43C6E2")
    expect(aircraftTitle(plane({ callsign: null, registration: null, hex: null }))).toBe(
      "Unknown aircraft",
    )
  })

  it("reads the numbers the way a transponder means them", () => {
    expect(aircraftFacts(plane())).toEqual([
      { label: "type", value: "A400" },
      { label: "role", value: "transport" },
      { label: "registration", value: "ZM413" },
      { label: "altitude", value: "24,000 ft" },
      { label: "speed", value: "451 kt" },
      { label: "track", value: "128°" },
      { label: "squawk", value: "6154" },
      { label: "hex", value: "43C6E2" },
    ])
  })

  //: A field the transponder never sent must not appear as a blank row: an
  //: empty value reads as a measurement of nothing rather than as silence.
  it("leaves out what was never transmitted", () => {
    expect(
      aircraftFacts(plane({ type: null, role: "other", alt_ft: null, squawk: null })),
    ).toEqual([
      { label: "registration", value: "ZM413" },
      { label: "speed", value: "451 kt" },
      { label: "track", value: "128°" },
      { label: "hex", value: "43C6E2" },
    ])
  })

  it("says on the ground rather than nought feet", () => {
    expect(aircraftFacts(plane({ alt_ft: 0 }))).toContainEqual({
      label: "altitude",
      value: "on the ground",
    })
  })
})
