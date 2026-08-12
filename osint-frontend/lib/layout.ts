/** The left column's geometry, in one place (#938).
 *
 *  The search bar sits at the top of the column and the deck sits under it,
 *  and they have to be the same width or the column reads as two unrelated
 *  things stacked by accident. Two files each holding their own copy of that
 *  width is how they drift, so both read this.
 */

/** Deck, search bar and detail pop-out all share it, so the pop-out lines up
 *  with the deck without measuring anything at runtime (#503). Widened once
 *  the column started hiding itself for the map — the reason to keep it narrow
 *  was that it was always there, and it no longer always is. */
export const PANEL_WIDTH = "clamp(360px, 32vw, 520px)"

/** Where the column's contents start: below the search bar, which is the one
 *  thing in the column that never goes away. A measured value would be more
 *  honest, but it would also mean the deck's position depends on a layout
 *  effect in a component it does not know about. */
export const COLUMN_TOP = "4rem"
