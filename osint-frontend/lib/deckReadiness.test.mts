import { describe, it, expect } from "vitest"
import { deckKeys, scoreboardIsReady } from "./deckReadiness"

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

describe("deckKeys", () => {
  it("is two cards when nothing is selected and nothing has graded", () => {
    expect(deckKeys({ hasSelection: false, scoreboardReady: false })).toEqual([
      "situation",
      "world",
    ])
  })

  it("gains the selection card only while something is picked", () => {
    expect(deckKeys({ hasSelection: true, scoreboardReady: false })).toEqual([
      "situation",
      "world",
      "selection",
    ])
  })

  it("keeps the standing cards in place when a selection appears", () => {
    // A card that shoved situation and world sideways on every map click would
    // stop the deck being somewhere you can learn your way around.
    const before = deckKeys({ hasSelection: false, scoreboardReady: false })
    const after = deckKeys({ hasSelection: true, scoreboardReady: false })
    expect(after.slice(0, before.length)).toEqual(before)
  })

  it("appends the scoreboard once it has something graded", () => {
    expect(deckKeys({ hasSelection: false, scoreboardReady: true })).toEqual([
      "situation",
      "world",
      "scoreboard",
    ])
  })

  it("carries both extras without disturbing the first two", () => {
    expect(deckKeys({ hasSelection: true, scoreboardReady: true })).toEqual([
      "situation",
      "world",
      "selection",
      "scoreboard",
    ])
  })
})
