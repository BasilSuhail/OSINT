/** Which edge a keypress puts away, and which it brings back (#938).
 *
 * The four panels sit on the four edges of the map, and until now each one
 * answered to a different key — `[` for the filter rail, `]` for the deck, and
 * nothing at all for the scrubber, whose hidden state lived inside its own
 * component. Three conventions for one gesture is three things to remember.
 *
 * WASD is the gesture people already have for "the four directions", and it
 * maps onto the edges without being taught: the key is where the panel is.
 * The old bracket keys keep working — they are in muscle memory and cost one
 * line each to honour.
 *
 * Pure so the mapping can be tested without a keyboard: the caller owns the
 * "are we typing" question, which is not something this file can see.
 */

export type PanelSide = "top" | "left" | "bottom" | "right"

const BY_KEY: Record<string, PanelSide> = {
  w: "top",
  a: "left",
  s: "bottom",
  d: "right",
  //: Kept from before WASD. `[` was the filter rail and `]` the deck, and a
  //: reader who has those in their hands should not have to relearn them.
  "[": "right",
  "]": "left",
}

/** The edge this key toggles, or null if the key means nothing here.
 *
 *  Case-insensitive: a held shift is a modifier on the gesture, not a
 *  different gesture. Any other modifier is somebody else's shortcut — ⌘S is
 *  save, not "hide the scrubber" — so those are declined.
 */
export function panelForKey(
  key: string,
  modifiers: { ctrl?: boolean; meta?: boolean; alt?: boolean } = {},
): PanelSide | null {
  if (modifiers.ctrl || modifiers.meta || modifiers.alt) return null
  return BY_KEY[key.toLowerCase()] ?? null
}
