/** When a held finger means what a right-click means (#946).
 *
 *  Right-click on the map asks what a place *is*; left-click asks what is
 *  *happening* near it (#862). A phone has no right-click. Android raises
 *  `contextmenu` for a long press, so the question half worked there by
 *  accident; mobile Safari does not raise it over a canvas, so on an iPhone
 *  it could not be asked at all.
 *
 *  Long press is the same question, not a new one. Everything here is a rule
 *  about whether a sequence of touches was a press — no React, no DOM, so the
 *  rules are the part a test can reach. The wiring is not.
 */

/** How long a finger has to stay down. Long enough not to fire during the
 *  first moment of a pan, short enough that a reader who is holding still is
 *  not left wondering whether anything is going to happen. */
export const LONG_PRESS_MS = 500

/** How far it may drift while doing so. A held finger is never still — it
 *  rolls a few pixels on the glass — and a threshold of zero would mean the
 *  gesture works for nobody. */
export const MOVE_TOLERANCE_PX = 10

/** How long after firing a press the native menu is ignored. Android raises
 *  `contextmenu` for the same gesture we just handled, and a place panel that
 *  opens twice for one press is a bug that only appears on one of the two
 *  platforms — which is the kind that gets shipped. */
export const SUPPRESS_CONTEXTMENU_MS = 700

export interface Point {
  x: number
  y: number
}

/** Whether the finger has travelled far enough to be panning rather than
 *  holding. Straight-line distance, not each axis on its own: nine pixels
 *  right and nine down is inside a per-axis tolerance twice over and is
 *  nearly thirteen pixels of travel, which is a pan leaving at 45 degrees. */
export function movedTooFar(from: Point, to: Point): boolean {
  return Math.hypot(to.x - from.x, to.y - from.y) > MOVE_TOLERANCE_PX
}

export interface PressState {
  /** Fingers currently on the glass. */
  touches: number
  elapsedMs: number
  from: Point
  to: Point
}

/** Whether what has happened so far is still a long press.
 *
 *  Every way out is a gesture that already means something else: a second
 *  finger is a pinch, travel is a pan, and lifting early is a tap — which
 *  opens the selection the map has always opened. This only ever adds a
 *  meaning to a gesture that had none.
 */
export function pressSurvives({ touches, elapsedMs, from, to }: PressState): boolean {
  if (touches !== 1) return false
  if (elapsedMs < LONG_PRESS_MS) return false
  return !movedTooFar(from, to)
}

/** Whether a `contextmenu` arriving at `nowMs` is the native echo of a press
 *  we have already handled. `lastPressMs` is null when none has fired, which
 *  is the desktop case: a real right-click, always let through. */
export function suppressesContextMenu(lastPressMs: number | null, nowMs: number): boolean {
  if (lastPressMs === null) return false
  return nowMs - lastPressMs < SUPPRESS_CONTEXTMENU_MS
}
