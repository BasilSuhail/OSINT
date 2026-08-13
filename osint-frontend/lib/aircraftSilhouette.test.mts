import { describe, expect, it } from "vitest"
import { aircraftSilhouette } from "./aircraftSilhouette"

describe("reading the airframe out of an ICAO type designator", () => {
  it("knows the transports and the fighters as fixed wing", () => {
    expect(aircraftSilhouette("C30J")).toBe("fixed-wing")
    expect(aircraftSilhouette("A400")).toBe("fixed-wing")
    expect(aircraftSilhouette("K35R")).toBe("fixed-wing")
    expect(aircraftSilhouette("F16")).toBe("fixed-wing")
    expect(aircraftSilhouette("EUFI")).toBe("fixed-wing")
    expect(aircraftSilhouette("P8")).toBe("fixed-wing")
  })

  it("knows the rotorcraft the list names", () => {
    expect(aircraftSilhouette("A139")).toBe("rotorcraft")
    expect(aircraftSilhouette("AS65")).toBe("rotorcraft")
    expect(aircraftSilhouette("R44")).toBe("rotorcraft")
    expect(aircraftSilhouette("S92")).toBe("rotorcraft")
    expect(aircraftSilhouette("LYNX")).toBe("rotorcraft")
  })

  //: The designator carries no class field, so the families that happen to be
  //: entirely rotorcraft are matched by prefix rather than typed out one model
  //: at a time — H60 and H64 and H47 are the same rule, not three entries.
  it("reads the whole-family prefixes as rotorcraft", () => {
    expect(aircraftSilhouette("H60")).toBe("rotorcraft")
    expect(aircraftSilhouette("H47")).toBe("rotorcraft")
    expect(aircraftSilhouette("EC35")).toBe("rotorcraft")
    expect(aircraftSilhouette("MI24")).toBe("rotorcraft")
    expect(aircraftSilhouette("KA52")).toBe("rotorcraft")
  })

  //: Every rotorcraft type in one live sample of the feed — 145 aircraft, 64
  //: designators, read off the presence endpoint while this was written. The
  //: sample is the only evidence that the rules cover what actually flies,
  //: rather than what a list of famous helicopters would suggest.
  it("catches the rotorcraft in a measured live sample", () => {
    for (const code of ["EC35", "H60", "H47", "H64", "EC45", "NH90", "MI8", "A139", "H53S", "W3"]) {
      expect(aircraftSilhouette(code)).toBe("rotorcraft")
    }
  })

  //: H25B is a Hawker business jet. It sits inside the H-and-a-digit prefix and
  //: is the reason that prefix cannot be trusted on its own.
  it("does not let the H prefix swallow the Hawkers", () => {
    expect(aircraftSilhouette("H25B")).toBe("fixed-wing")
    expect(aircraftSilhouette("H25C")).toBe("fixed-wing")
  })

  it("reads the designator however the feed cased and spaced it", () => {
    expect(aircraftSilhouette(" ec45 ")).toBe("rotorcraft")
    expect(aircraftSilhouette("c17")).toBe("fixed-wing")
  })

  //: A designator the rotorcraft list has not been taught is a wing. No list
  //: of names covers a feed that carries every military type flying, and the
  //: rotorcraft side is matched by family as well as by name, so what is left
  //: over is overwhelmingly fixed wing.
  it("gives a wing to a designator the rotorcraft list does not name", () => {
    expect(aircraftSilhouette("ZZZ9")).toBe("fixed-wing")
  })

  //: Nothing sent, nothing claimed. This is the one case the third shape is
  //: true of, and it is the same rule that stops an absent track from being
  //: rotated to north.
  it("says unknown only when the feed sent no designator", () => {
    expect(aircraftSilhouette(null)).toBe("unknown")
    expect(aircraftSilhouette(undefined)).toBe("unknown")
    expect(aircraftSilhouette("   ")).toBe("unknown")
  })
})
