/** The phone layout's arithmetic, in one place (#942).
 *
 *  The console can be opened over the local network on a phone. That screen
 *  gets the map, one search bar across the top, and everything else put away
 *  until it is asked for — the deck arrives as a sheet along the bottom edge
 *  rather than as a panel over the map it describes.
 *
 *  Everything here is a number the layout needs and nothing here touches
 *  React or the DOM. That is deliberate: the rest of the narrow layout is
 *  visual and can only be checked by looking at it on a phone, so the parts
 *  that can be stated as arithmetic are separated out where a test reaches
 *  them.
 */

/** Below this the console is a phone, not a narrow window. Lower than the
 *  900px the two-pane switcher used, because between the two a laptop window
 *  dragged narrow is still a laptop and has a cursor. */
export const NARROW_MAX_PX = 820

export const NARROW_QUERY = `(max-width: ${NARROW_MAX_PX}px)`

/** The sheet at rest: a grip and the title of whichever card is showing. Any
 *  taller and it is a panel the reader has to put away before using the map. */
export const PEEK_PX = 56

/** What the sheet never covers, however far it is opened: the search bar.
 *  Matches `COLUMN_TOP` — the same bar, measured the same way. */
export const TOP_STRIP_PX = 64

/** Above this speed a drag is a throw rather than a placement, and where it
 *  was released stops deciding where it lands. */
export const FLICK_PX_PER_S = 500

export type Detent = "peek" | "half" | "full"

/** Low to high. The order a flick steps through. */
const ORDER: Detent[] = ["peek", "half", "full"]

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high)
}

/** How tall the sheet stands at each detent, for a viewport of `viewportH`.
 *
 *  Total for every input, including the zero a phone reports for a frame
 *  mid-rotation: the heights collapse onto each other rather than crossing,
 *  so the sheet is briefly one height instead of briefly inside out.
 */
export function detentHeights(viewportH: number): Record<Detent, number> {
  const full = Math.max(0, viewportH - TOP_STRIP_PX)
  const peek = Math.min(PEEK_PX, full)
  const half = clamp(viewportH / 2, peek, full)
  return { peek, half, full }
}

/** Which detent a drag released at `height` px with `velocity` px/s lands on.
 *  Positive velocity is upward — the sheet growing.
 *
 *  A slow drag takes the nearest detent: the reader placed it. A flick moves
 *  one detent from the nearest in the direction of travel, and only one —
 *  a gesture that overshoots from peek to full is a gesture that has to be
 *  undone, and undoing it is a second gesture the reader did not ask for.
 */
export function snapDetent(height: number, viewportH: number, velocity: number): Detent {
  const heights = detentHeights(viewportH)
  let nearestIndex = 0
  let nearestGap = Infinity
  ORDER.forEach((detent, index) => {
    const gap = Math.abs(heights[detent] - height)
    if (gap < nearestGap) {
      nearestGap = gap
      nearestIndex = index
    }
  })

  if (Math.abs(velocity) <= FLICK_PX_PER_S) return ORDER[nearestIndex]

  const step = velocity > 0 ? 1 : -1
  return ORDER[clamp(nearestIndex + step, 0, ORDER.length - 1)]
}

/** What the four edges hold when the console opens on a phone.
 *
 *  The rail and the scrubber both default to showing, which is right on a
 *  desktop where they cost a strip of a large map and wrong here where they
 *  cost two of four short edges. Both keep the handles they already have, so
 *  starting closed hides them rather than removing them.
 */
export function narrowInitialPanels(): { bottom: boolean; right: boolean } {
  return { bottom: false, right: false }
}
