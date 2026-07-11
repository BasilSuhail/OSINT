import { describe, expect, it } from "vitest"

import {
  contestedVerdict,
  scoreboardVerdict,
  storyVerdict,
} from "@/lib/verdicts"

describe("storyVerdict", () => {
  it("sensor-backed multi-owner stories read as verified", () => {
    const v = storyVerdict({ owner_count: 13, corroboration: 0.99, confirmed: ["earthquake"] })
    expect(v).toContain("13 independent organisations")
    expect(v.toLowerCase()).toContain("physical sensor")
    expect(v.toLowerCase()).toContain("as close to verified")
  })

  it("strong but unsensed stories read as strongly corroborated", () => {
    const v = storyVerdict({ owner_count: 4, corroboration: 0.875, confirmed: [] })
    expect(v).toContain("4 independent organisations")
    expect(v.toLowerCase()).toContain("strongly corroborated")
  })

  it("two-owner stories read as probably real", () => {
    const v = storyVerdict({ owner_count: 2, corroboration: 0.5, confirmed: [] })
    expect(v.toLowerCase()).toContain("probably real")
  })

  it("weak scores read as worth a look, not solid", () => {
    const v = storyVerdict({ owner_count: 1, corroboration: 0.3, confirmed: [] })
    expect(v.toLowerCase()).toContain("worth a look")
  })

  it("single-source stories read as rumour", () => {
    const v = storyVerdict({ owner_count: 1, corroboration: 0, confirmed: [] })
    expect(v.toLowerCase()).toContain("rumour")
    expect(v.toLowerCase()).toContain("one organisation")
  })
})

describe("contestedVerdict", () => {
  it("names the two biggest blocs in full and flags the divergence", () => {
    const v = contestedVerdict({ divergence: 0.885, groups: { GB: 4, RU: 4, FR: 1 } })
    expect(v).toContain("United Kingdom")
    expect(v).toContain("Russia")
    expect(v.toLowerCase()).toContain("very differently")
  })

  it("moderate divergence softens the wording", () => {
    const v = contestedVerdict({ divergence: 0.4, groups: { GB: 1, JP: 1 } })
    expect(v.toLowerCase()).toContain("somewhat differently")
  })
})

describe("scoreboardVerdict", () => {
  it("no grades yet reads as record being earned", () => {
    expect(scoreboardVerdict(0, null).toLowerCase()).toContain("still being earned")
  })

  it("coin-flip brier says so plainly", () => {
    const v = scoreboardVerdict(120, 0.25)
    expect(v.toLowerCase()).toContain("indistinguishable from guessing")
  })

  it("a winning brier is stated with the number", () => {
    const v = scoreboardVerdict(120, 0.12)
    expect(v).toContain("0.120")
    expect(v.toLowerCase()).toContain("better than guessing")
  })
})
