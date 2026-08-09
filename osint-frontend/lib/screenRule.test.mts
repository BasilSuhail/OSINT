import { describe, expect, it } from "vitest"
import { deckPageKeys } from "./deckPages"

/**
 * The operator's rule, as tests:
 *
 *   screen 1  news and stories          left column
 *   screen 2  world view and search     left column
 *   screen 3  made by a map click       left column
 *   screen 4  THE POP-UP                a second column, beside the left one
 *
 *   Clicking anything on 1, 2 or 3 that needs expanding opens screen 4 beside
 *   it. The screen you clicked from stays visible and does not move.
 *   Escape closes screen 4 and nothing else.
 */
const SCREEN_1 = 0
const SCREEN_2 = 1
const SCREEN_3 = 2

describe("the left column", () => {
  it("is screen 1, then 2, then 3 when a map click makes it", () => {
    const keys = deckPageKeys({ selection: true, scoreboard: false })
    expect(keys[SCREEN_1]).toBe("situation")
    expect(keys[SCREEN_2]).toBe("world")
    expect(keys[SCREEN_3]).toBe("selection")
  })

  it("has no screen 3 until the map is clicked", () => {
    expect(deckPageKeys({ selection: false, scoreboard: false })).toEqual(["situation", "world"])
  })

  it("never moves screens 1 and 2", () => {
    for (const selection of [false, true]) {
      for (const scoreboard of [false, true]) {
        const keys = deckPageKeys({ selection, scoreboard })
        expect(keys[SCREEN_1]).toBe("situation")
        expect(keys[SCREEN_2]).toBe("world")
      }
    }
  })
})

describe("the pop-up", () => {
  it("is never a page in the left column", () => {
    // Screen 4 is a second column. Making it a page here is what hid screen 3
    // behind it every time a row was clicked.
    for (const selection of [false, true]) {
      for (const scoreboard of [false, true]) {
        expect(deckPageKeys({ selection, scoreboard })).not.toContain("popup")
      }
    }
  })

  it("cannot change how many pages the left column has", () => {
    // Opening or closing it must not add, remove or renumber a page — which
    // is what made Escape land on screen 2.
    const before = deckPageKeys({ selection: true, scoreboard: false })
    const after = deckPageKeys({ selection: true, scoreboard: false })
    expect(after).toEqual(before)
    expect(after).toHaveLength(3)
  })
})
