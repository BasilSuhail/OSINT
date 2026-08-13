/** What changes when the console is opened on a phone (#942, #944).
 *
 *  Nothing moves. The deck is still the left column, the filter rail is still
 *  docked right, the scrubber still runs along the bottom, and each still has
 *  the handle it already had. What changes is that all three arrive put away
 *  instead of open, and that the column takes the width of the screen because
 *  there is no other width available.
 *
 *  An earlier pass replaced the deck with a bottom sheet. That was a second
 *  layout to learn, and a reader who knows the console on a laptop had to
 *  learn it twice. One console, sized down.
 *
 *  No React and no DOM here, so the decisions this file holds are the ones a
 *  test can reach. The rest is visual and has to be looked at on a phone.
 */

/** Below this the console is a phone, not a narrow window. Lower than the
 *  900px the old two-pane switcher used, because between the two a laptop
 *  window dragged narrow is still a laptop and still has a cursor. */
export const NARROW_MAX_PX = 820

export const NARROW_QUERY = `(max-width: ${NARROW_MAX_PX}px)`

/** What the four edges hold when the console opens on a phone.
 *
 *  All three panels default to showing, which is right beside a large map and
 *  wrong here, where any one of them is most of the screen. `top` stays true:
 *  it is the omnibox's result list, which is empty until something is typed,
 *  and starting it collapsed would mean a first search that answers into a
 *  panel the reader then has to find and open.
 *
 *  Applied once, on arrival. This is where the console starts, not a rule
 *  about where it has to stay — putting any of them back keeps it back.
 */
export function narrowInitialPanels(): { left: boolean; bottom: boolean; right: boolean } {
  return { left: false, bottom: false, right: false }
}
