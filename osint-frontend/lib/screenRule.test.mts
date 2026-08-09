import { describe, expect, it } from "vitest"
import { deckPageKeys, pageAfterPopupCloses, pageForPopup } from "./deckPages"

/**
 * The operator's rule, written as tests so the next change breaks a test
 * rather than a screen (#850):
 *
 *   screen 1  news and stories
 *   screen 2  world view and search
 *   screen 3  created by clicking the map
 *   screen 4  the pop-up
 *
 *   Anything clicked on 1, 2 or 3 that needs detail opens the pop-up.
 *   Escape closes the pop-up only, and leaves the reader on screen 3 —
 *   or screen 1 when screen 3 is not open.
 */
const SCREEN_1 = 0
const SCREEN_2 = 1
const SCREEN_3 = 2
const SCREEN_4 = 3

describe("the four screens", () => {
  it("numbers them the way the operator does", () => {
    const keys = deckPageKeys({ selection: true, popup: true, scoreboard: false })
    expect(keys[SCREEN_1]).toBe("situation")
    expect(keys[SCREEN_2]).toBe("world")
    expect(keys[SCREEN_3]).toBe("selection")
    expect(keys[SCREEN_4]).toBe("popup")
  })

  it("keeps screen 1 and 2 fixed whatever else is open", () => {
    for (const selection of [false, true]) {
      for (const popup of [false, true]) {
        const keys = deckPageKeys({ selection, popup, scoreboard: true })
        expect(keys[SCREEN_1]).toBe("situation")
        expect(keys[SCREEN_2]).toBe("world")
      }
    }
  })
})

describe("opening a pop-up", () => {
  it("lands on screen 4 when screen 3 is open", () => {
    expect(pageForPopup({ selection: true, popup: true, scoreboard: false })).toBe(SCREEN_4)
  })

  it("lands on screen 3's slot when there is no screen 3", () => {
    // Without a map selection the pop-up is the third page. It is still "the
    // pop-up"; only its index moves.
    expect(pageForPopup({ selection: false, popup: true, scoreboard: false })).toBe(SCREEN_3)
  })
})

describe("closing the pop-up", () => {
  it("returns to screen 3 when it is open", () => {
    expect(pageAfterPopupCloses({ selection: true, scoreboard: false })).toBe(SCREEN_3)
  })

  it("returns to screen 1 when screen 3 is closed", () => {
    expect(pageAfterPopupCloses({ selection: false, scoreboard: false })).toBe(SCREEN_1)
  })

  it("never leaves the reader on screen 2", () => {
    // The reported defect. Screen 2 is where the scroll clamp used to land.
    for (const selection of [false, true]) {
      for (const scoreboard of [false, true]) {
        expect(pageAfterPopupCloses({ selection, scoreboard })).not.toBe(SCREEN_2)
      }
    }
  })

  it("does not remove screen 3", () => {
    const before = deckPageKeys({ selection: true, popup: true, scoreboard: false })
    const after = deckPageKeys({ selection: true, popup: false, scoreboard: false })
    expect(before).toContain("selection")
    expect(after).toContain("selection")
  })
})
