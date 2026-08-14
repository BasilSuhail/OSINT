import { describe, expect, it } from "vitest"
import {
  aircraftFacts,
  airborneLabel,
  militaryLabel,
  roleLabel,
  watchlistHint,
  type PresenceAircraft,
} from "./presence"

const aircraft = (over: Partial<PresenceAircraft> = {}): PresenceAircraft => ({
  hex: "ae6472",
  callsign: "KING98",
  type: "K35R",
  registration: "17-5898",
  lat: 61,
  lon: -149.8,
  track: 202,
  alt_ft: 21000,
  speed_kt: 380,
  squawk: null,
  kind: "military",
  role: "tanker",
  watch: null,
  airborne_since: null,
  ...over,
})

describe("saying what an aircraft is for", () => {
  it("puts the role in words", () => {
    expect(roleLabel("tanker")).toBe("tanker")
    expect(roleLabel("isr")).toBe("surveillance")
  })

  //: A designator the backend was never taught reaches here as `other`, and
  //: printing a role for it would put a fact on the card that nothing measured.
  it("says nothing for a role that was never read", () => {
    expect(roleLabel("other")).toBeNull()
  })

  it("carries the role into the card's facts", () => {
    const facts = aircraftFacts(aircraft())
    expect(facts).toContainEqual({ label: "role", value: "tanker" })
  })

  it("leaves the role out when the designator said nothing", () => {
    const facts = aircraftFacts(aircraft({ role: "other" }))
    expect(facts.map((f) => f.label)).not.toContain("role")
  })
})

describe("how long the console has seen something flying", () => {
  const start = Date.parse("2026-08-13T10:00:00Z")

  it("counts from when it was first seen, in minutes then hours", () => {
    expect(airborneLabel("2026-08-13T10:00:00Z", start + 30 * 60_000)).toBe(
      "seen flying for 30m",
    )
    expect(airborneLabel("2026-08-13T10:00:00Z", start + 90 * 60_000)).toBe(
      "seen flying for 1h 30m",
    )
    expect(airborneLabel("2026-08-13T10:00:00Z", start + 120 * 60_000)).toBe(
      "seen flying for 2h",
    )
  })

  it("has nothing to say about an aircraft nobody is watching", () => {
    expect(airborneLabel(null, start)).toBeNull()
  })

  it("does not turn an unreadable timestamp into a number", () => {
    expect(airborneLabel("not a time", start)).toBeNull()
  })

  //: A clock that has only just started still says something true.
  it("says just now rather than zero", () => {
    expect(airborneLabel("2026-08-13T10:00:00Z", start + 5_000)).toBe("seen flying just now")
  })
})

describe("explaining an empty watchlist layer", () => {
  //: The two ways to draw nothing, which look identical on a map.
  it("distinguishes nobody watching from nothing airborne", () => {
    expect(watchlistHint(0, 0)).toBe("none watched — add data/watchlist.json")
    expect(watchlistHint(4, 0)).toBe("4 watched · none airborne")
  })

  it("counts one airframe in the singular", () => {
    expect(watchlistHint(1, 0)).toBe("1 watched · none airborne")
  })

  //: Nothing to explain once there are marks on the map.
  it("says nothing when the layer is drawing something", () => {
    expect(watchlistHint(4, 2)).toBeNull()
    expect(watchlistHint(0, 1)).toBeNull()
  })
})

describe("whose claim military is", () => {
  //: The feed's list is a database flag covering state and head-of-state
  //: transports as well as air forces, so an airliner on it is the flag
  //: working. The card must not restate that as this console's finding.
  it("attributes the flag rather than asserting it", () => {
    expect(militaryLabel()).toBe("flagged military by the feed")
  })
})

describe("whose list is being followed", () => {
  //: A reader is owed the difference between "these are the aircraft you asked
  //: for" and "these are the ones this console follows until told otherwise" —
  //: said whether or not anything is on screen.
  it("says so when the built-in list is in force", () => {
    expect(watchlistHint(2, 0, "default")).toBe("tankers and surveillance — the default list")
    expect(watchlistHint(2, 6, "default")).toBe("tankers and surveillance — the default list")
  })

  it("says nothing extra when somebody wrote the list", () => {
    expect(watchlistHint(3, 2, "ok")).toBeNull()
  })
})
