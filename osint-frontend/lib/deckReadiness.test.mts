import { describe, it, expect } from "vitest"
import { scoreboardIsReady } from "./deckReadiness"

describe("scoreboardIsReady", () => {
  it("is not ready while nothing has been graded", () => {
    // The live shape today: 167 issued at each horizon, every Brier null.
    expect(
      scoreboardIsReady([{ graded: 0 }, { graded: 0 }, { graded: 0 }]),
    ).toBe(false)
  })

  it("becomes ready as soon as one prediction grades", () => {
    expect(scoreboardIsReady([{ graded: 0 }, { graded: 3 }])).toBe(true)
  })

  it("treats a still-loading response as not ready", () => {
    // Otherwise the card flashes in and out on first paint.
    expect(scoreboardIsReady(undefined)).toBe(false)
  })

  it("treats an empty scoreboard as not ready", () => {
    expect(scoreboardIsReady([])).toBe(false)
  })

  it("treats a null graded count as zero rather than throwing", () => {
    expect(scoreboardIsReady([{ graded: null }])).toBe(false)
  })
})
