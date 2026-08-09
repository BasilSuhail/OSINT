/** What pages the deck has, and in what order (#842).
 *
 * The deck is a place a reader learns: page two is always the world, and the
 * page they were on stays where they left it. Two rules follow, and both have
 * been broken in use.
 *
 * **Transient pages are appended, never inserted.** Putting a new page before
 * an existing one shoves every page after it sideways, so the reader's page
 * number silently means something else. This is the constraint the selection
 * card was written against and the story page now obeys.
 *
 * **A page is never replaced by another surface.** Opening a story used to
 * swap the entire deck for the story card, which destroyed the selection the
 * reader had open and left nothing to swipe back to.
 *
 * Kept as a pure function so the ordering can be asserted without a browser —
 * the composition is the part that goes wrong, not the pixels.
 */
export interface DeckState {
  /** Something on the map is picked. */
  selection: boolean
  /** Something is popped up beside what the reader was reading — a story, a
   *  country, the world detail. All of them land in one place (#846). */
  popup: boolean
  /** The scoreboard has something graded to show. */
  scoreboard: boolean
}

export type DeckPageKey = "situation" | "world" | "selection" | "popup" | "scoreboard"

/** The pop-up page. Stated as a named invariant because three consecutive
 *  changes each satisfied the request in front of them and moved something
 *  else: **page four is the pop-up, whatever opened it, and Escape closes it
 *  and nothing else** (#846). */
export const POPUP_PAGE: DeckPageKey = "popup"

/** The standing pages, always present and always first. */
export const STANDING_PAGES: readonly DeckPageKey[] = ["situation", "world"] as const

export function deckPageKeys(state: DeckState): DeckPageKey[] {
  const keys: DeckPageKey[] = [...STANDING_PAGES]
  if (state.selection) keys.push("selection")
  if (state.popup) keys.push(POPUP_PAGE)
  if (state.scoreboard) keys.push("scoreboard")
  return keys
}


/** Where the deck should be after the pop-up closes (#850).
 *
 * Not wherever a scroll clamp happens to land. Removing the pop-up shortens
 * the track, the browser clamps `scrollLeft` to the new maximum, and the
 * reader ends up on whatever page happens to be last — screen 2 when no
 * selection is open. That is a page nobody chose.
 *
 * The rule is the operator's: back to screen 3, or screen 1 when screen 3 is
 * not open.
 */
export function pageAfterPopupCloses(state: Omit<DeckState, "popup">): number {
  const keys = deckPageKeys({ ...state, popup: false })
  const selection = keys.indexOf("selection")
  return selection >= 0 ? selection : 0
}

/** Where the deck should be when a pop-up opens: on the pop-up. */
export function pageForPopup(state: DeckState): number {
  return deckPageKeys(state).indexOf(POPUP_PAGE)
}
