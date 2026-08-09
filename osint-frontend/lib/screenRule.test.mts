import { describe, expect, it } from "vitest"
import { deckPageKeys } from "./deckPages"

/**
 * The operator's rule, as tests:
 *
 *   screen 1  news and stories            left column
 *   screen 2  world view and search       left column
 *   screen 3  made by a map click         left column
 *   screen 4  made by a map right-click   left column
 *
 *   The pop-up is not on this list. It is a pop-up: it opens over what you
 *   were reading and goes away again. Numbering it is the confusion that
 *   #843-#853 spent five pull requests undoing.
 *
 *   Clicking anything on a screen that needs expanding opens the pop-up beside
 *   it. The screen you clicked from stays visible and does not move. Escape
 *   closes the pop-up and nothing else.
 */
const SCREEN_1 = 0
const SCREEN_2 = 1
const SCREEN_3 = 2
const SCREEN_4 = 3

describe("the left column", () => {
  it("is screen 1, then 2, then 3 when a map click makes it", () => {
    const keys = deckPageKeys({ selection: true, place: false, scoreboard: false })
    expect(keys[SCREEN_1]).toBe("situation")
    expect(keys[SCREEN_2]).toBe("world")
    expect(keys[SCREEN_3]).toBe("selection")
  })

  it("has no screen 3 until the map is clicked", () => {
    expect(deckPageKeys({ selection: false, place: false, scoreboard: false })).toEqual([
      "situation",
      "world",
    ])
  })

  it("never moves screens 1 and 2", () => {
    for (const selection of [false, true]) {
      for (const place of [false, true]) {
        for (const scoreboard of [false, true]) {
          const keys = deckPageKeys({ selection, place, scoreboard })
          expect(keys[SCREEN_1]).toBe("situation")
          expect(keys[SCREEN_2]).toBe("world")
        }
      }
    }
  })
})

describe("the place screen", () => {
  it("is not there until the map is right-clicked", () => {
    expect(deckPageKeys({ selection: true, place: false, scoreboard: false })).not.toContain("place")
  })

  it("is screen 4 when a map click already made screen 3", () => {
    const keys = deckPageKeys({ selection: true, place: true, scoreboard: false })
    expect(keys[SCREEN_4]).toBe("place")
  })

  it("is screen 3 when nothing is selected", () => {
    const keys = deckPageKeys({ selection: false, place: true, scoreboard: false })
    expect(keys[SCREEN_3]).toBe("place")
  })

  it("always sits after the selection screen and before the scoreboard", () => {
    const keys = deckPageKeys({ selection: true, place: true, scoreboard: true })
    expect(keys.indexOf("place")).toBeGreaterThan(keys.indexOf("selection"))
    expect(keys.indexOf("place")).toBeLessThan(keys.indexOf("scoreboard"))
  })

  it("does not move the selection screen when it appears", () => {
    // Opening a place must not shove the list a map click built sideways.
    const before = deckPageKeys({ selection: true, place: false, scoreboard: true })
    const after = deckPageKeys({ selection: true, place: true, scoreboard: true })
    expect(after.indexOf("selection")).toBe(before.indexOf("selection"))
  })
})

describe("the pop-up", () => {
  it("is never a page in the left column", () => {
    // It is a pop-up. Making it a page here is what hid screen 3 behind it
    // every time a row was clicked.
    for (const selection of [false, true]) {
      for (const place of [false, true]) {
        for (const scoreboard of [false, true]) {
          expect(deckPageKeys({ selection, place, scoreboard })).not.toContain("popup")
        }
      }
    }
  })

  it("cannot change how many pages the left column has", () => {
    // Opening or closing it must not add, remove or renumber a page — which
    // is what made Escape land on screen 2.
    const before = deckPageKeys({ selection: true, place: false, scoreboard: false })
    const after = deckPageKeys({ selection: true, place: false, scoreboard: false })
    expect(after).toEqual(before)
    expect(after).toHaveLength(3)
  })
})
