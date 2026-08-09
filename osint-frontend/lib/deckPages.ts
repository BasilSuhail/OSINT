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
  /** A story is open. */
  story: boolean
  /** The scoreboard has something graded to show. */
  scoreboard: boolean
}

export type DeckPageKey = "situation" | "world" | "selection" | "story" | "scoreboard"

/** The standing pages, always present and always first. */
export const STANDING_PAGES: readonly DeckPageKey[] = ["situation", "world"] as const

export function deckPageKeys(state: DeckState): DeckPageKey[] {
  const keys: DeckPageKey[] = [...STANDING_PAGES]
  if (state.selection) keys.push("selection")
  if (state.story) keys.push("story")
  if (state.scoreboard) keys.push("scoreboard")
  return keys
}
