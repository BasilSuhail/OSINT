import { describe, expect, it } from "vitest"
import {
  deckPageKeys,
  pageAfterPopupCloses,
  pageForPopup,
  STANDING_PAGES,
} from "./deckPages"

const state = (over: Partial<Parameters<typeof deckPageKeys>[0]> = {}) => ({
  selection: false,
  popup: false,
  scoreboard: false,
  ...over,
})

describe("what pages the deck has", () => {
  it("is the same page whatever popped up", () => {
    // A story, a country and the world detail are one slot (#846). Two names
    // for the pop-up is how the collapse handle ended up in open map.
    expect(deckPageKeys(state({ popup: true }))).toContain("popup")
  })

  it("always starts with the standing pages", () => {
    expect(deckPageKeys(state())).toEqual([...STANDING_PAGES])
  })

  it("opening a story adds a page rather than replacing the deck", () => {
    // The reported defect: the story used to take over the whole surface, so
    // there was nothing to swipe back to.
    expect(deckPageKeys(state({ popup: true }))).toEqual(["situation", "world", "popup"])
  })

  it("keeps the selection page when a story opens on top of it", () => {
    const withSelection = deckPageKeys(state({ selection: true }))
    const withBoth = deckPageKeys(state({ selection: true, popup: true }))
    expect(withSelection).toEqual(["situation", "world", "selection"])
    expect(withBoth).toEqual(["situation", "world", "selection", "popup"])
  })

  it("puts the story after the selection, never before it", () => {
    // Inserting would renumber every page after it, and a deck whose pages
    // move is not a place you can learn.
    const keys = deckPageKeys(state({ selection: true, popup: true }))
    expect(keys.indexOf("popup")).toBeGreaterThan(keys.indexOf("selection"))
  })

  it("never moves the standing pages, whatever else is open", () => {
    const combos = [
      state({ selection: true }),
      state({ popup: true }),
      state({ scoreboard: true }),
      state({ selection: true, popup: true, scoreboard: true }),
    ]
    for (const combo of combos) {
      expect(deckPageKeys(combo).slice(0, 2)).toEqual([...STANDING_PAGES])
    }
  })

  it("closing the story leaves the reader a page to return to", () => {
    const open = deckPageKeys(state({ selection: true, popup: true }))
    const closed = deckPageKeys(state({ selection: true }))
    expect(open.slice(0, closed.length)).toEqual(closed)
  })
})

describe("where the deck should be looking", () => {
  it("puts the story last, so moving to it means moving forward", () => {
    // The deck scrolls to a newly created page. If a story could land before
    // an existing page, "go to the story" would sometimes mean going back.
    const keys = deckPageKeys({ selection: true, popup: true, scoreboard: true })
    expect(keys.indexOf("popup")).toBeGreaterThan(keys.indexOf("selection"))
    expect(keys.indexOf("popup")).toBeLessThan(keys.indexOf("scoreboard"))
  })

  it("gives the story a stable index while it is open", () => {
    // The index the deck scrolls to must not move underneath it because
    // something unrelated appeared.
    const before = deckPageKeys({ selection: true, popup: true, scoreboard: false })
    const after = deckPageKeys({ selection: true, popup: true, scoreboard: true })
    expect(after.indexOf("popup")).toBe(before.indexOf("popup"))
  })
})


describe("where the deck goes when the pop-up closes", () => {
  it("returns to screen 3 when a map selection is open", () => {
    // The reported defect: Escape landed on screen 2, because removing the
    // pop-up let the scroll clamp choose the page.
    expect(pageAfterPopupCloses({ selection: true, scoreboard: false })).toBe(2)
  })

  it("returns to screen 1 when there is no screen 3", () => {
    expect(pageAfterPopupCloses({ selection: false, scoreboard: false })).toBe(0)
  })

  it("is not the last page just because the last page exists", () => {
    // With a scoreboard present the clamp would have landed there too.
    expect(pageAfterPopupCloses({ selection: false, scoreboard: true })).toBe(0)
    expect(pageAfterPopupCloses({ selection: true, scoreboard: true })).toBe(2)
  })
})

describe("where the deck goes when the pop-up opens", () => {
  it("goes to the pop-up, wherever it landed", () => {
    expect(pageForPopup({ selection: true, popup: true, scoreboard: false })).toBe(3)
    expect(pageForPopup({ selection: false, popup: true, scoreboard: false })).toBe(2)
  })

  it("reports no page when nothing is popped up", () => {
    expect(pageForPopup({ selection: true, popup: false, scoreboard: false })).toBe(-1)
  })
})
