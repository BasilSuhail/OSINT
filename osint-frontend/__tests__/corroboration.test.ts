import { describe, expect, it } from "vitest"

import { confirmedClaims, corroborationTone } from "@/lib/analytics"

describe("corroborationTone", () => {
  it("dims unverified single-teller stories", () => {
    expect(corroborationTone(0)).toContain("neutral-500")
    expect(corroborationTone(null)).toContain("neutral-500")
  })

  it("steps up with the score", () => {
    expect(corroborationTone(0.5)).toContain("emerald")
    expect(corroborationTone(0.75)).toContain("cyan")
    expect(corroborationTone(0.9)).toContain("cyan")
  })
})

describe("confirmedClaims", () => {
  it("extracts only confirmed claim types", () => {
    expect(
      confirmedClaims({ earthquake: "confirmed", disaster: "unconfirmed" }),
    ).toEqual(["earthquake"])
  })

  it("empty map means no chips", () => {
    expect(confirmedClaims({})).toEqual([])
  })
})
