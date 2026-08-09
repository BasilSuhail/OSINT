import { describe, expect, it } from "vitest"
import { deckPageKeys, STANDING_PAGES } from "./deckPages"

const state = (over: Partial<Parameters<typeof deckPageKeys>[0]> = {}) => ({
  selection: false,
  story: false,
  scoreboard: false,
  ...over,
})

describe("what pages the deck has", () => {
  it("always starts with the standing pages", () => {
    expect(deckPageKeys(state())).toEqual([...STANDING_PAGES])
  })

  it("opening a story adds a page rather than replacing the deck", () => {
    // The reported defect: the story used to take over the whole surface, so
    // there was nothing to swipe back to.
    expect(deckPageKeys(state({ story: true }))).toEqual(["situation", "world", "story"])
  })

  it("keeps the selection page when a story opens on top of it", () => {
    const withSelection = deckPageKeys(state({ selection: true }))
    const withBoth = deckPageKeys(state({ selection: true, story: true }))
    expect(withSelection).toEqual(["situation", "world", "selection"])
    expect(withBoth).toEqual(["situation", "world", "selection", "story"])
  })

  it("puts the story after the selection, never before it", () => {
    // Inserting would renumber every page after it, and a deck whose pages
    // move is not a place you can learn.
    const keys = deckPageKeys(state({ selection: true, story: true }))
    expect(keys.indexOf("story")).toBeGreaterThan(keys.indexOf("selection"))
  })

  it("never moves the standing pages, whatever else is open", () => {
    const combos = [
      state({ selection: true }),
      state({ story: true }),
      state({ scoreboard: true }),
      state({ selection: true, story: true, scoreboard: true }),
    ]
    for (const combo of combos) {
      expect(deckPageKeys(combo).slice(0, 2)).toEqual([...STANDING_PAGES])
    }
  })

  it("closing the story leaves the reader a page to return to", () => {
    const open = deckPageKeys(state({ selection: true, story: true }))
    const closed = deckPageKeys(state({ selection: true }))
    expect(open.slice(0, closed.length)).toEqual(closed)
  })
})

describe("where the deck should be looking", () => {
  it("puts the story last, so moving to it means moving forward", () => {
    // The deck scrolls to a newly created page. If a story could land before
    // an existing page, "go to the story" would sometimes mean going back.
    const keys = deckPageKeys({ selection: true, story: true, scoreboard: true })
    expect(keys.indexOf("story")).toBeGreaterThan(keys.indexOf("selection"))
    expect(keys.indexOf("story")).toBeLessThan(keys.indexOf("scoreboard"))
  })

  it("gives the story a stable index while it is open", () => {
    // The index the deck scrolls to must not move underneath it because
    // something unrelated appeared.
    const before = deckPageKeys({ selection: true, story: true, scoreboard: false })
    const after = deckPageKeys({ selection: true, story: true, scoreboard: true })
    expect(after.indexOf("story")).toBe(before.indexOf("story"))
  })
})
