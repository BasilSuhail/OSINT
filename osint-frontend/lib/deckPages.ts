/** What pages the deck has, and in what order.
 *
 * The deck is the LEFT column: screen 1, screen 2, and screen 3 when a map
 * click creates it. Transient pages are appended, never inserted — a page put
 * before an existing one shoves every later page sideways, and a deck whose
 * pages move is not a place anyone can learn.
 *
 * **The pop-up is not in here.** Screen 4 is the pop-up, and it is a second
 * column beside this one, not a page inside it. It was briefly made a deck
 * page (#843–#851) and that hid screen 3 behind it every time something was
 * opened. Kept as a comment rather than a memory, because that is the mistake
 * this file exists to prevent repeating.
 */
export interface DeckState {
  /** Something on the map is picked — screen 3. */
  selection: boolean
  /** The scoreboard has something graded to show. */
  scoreboard: boolean
}

export type DeckPageKey = "situation" | "world" | "selection" | "scoreboard"

/** The standing pages, always present and always first. */
export const STANDING_PAGES: readonly DeckPageKey[] = ["situation", "world"] as const

export function deckPageKeys(state: DeckState): DeckPageKey[] {
  const keys: DeckPageKey[] = [...STANDING_PAGES]
  if (state.selection) keys.push("selection")
  if (state.scoreboard) keys.push("scoreboard")
  return keys
}
