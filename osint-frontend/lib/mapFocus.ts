// Focus mode — the map drawn around one hazard instead of all of them.
// Pure decisions only, no map dependency, so the rules are unit-testable.

import type { VisibleEvent } from "./queries"
import type { HazardFootprintCollection } from "./mapFootprints"

/** Share of its usual opacity a marker keeps while another hazard holds focus.
 *  Faded, not hidden: the reader must still see that neighbours exist, only
 *  that they are not the thing being read. */
export const FOCUS_DIM = 0.25

const NO_FOOTPRINTS: HazardFootprintCollection = { type: "FeatureCollection", features: [] }

/** Does clicking this row put the map into focus mode? Only rows that draw
 *  geometry. A news dot has no footprint, so isolating it would blank the map
 *  and leave nothing to look at. */
export function focusable(ev: Pick<VisibleEvent, "category">): boolean {
  return ev.category === "hazard" || ev.category === "weather"
}

/** Ambient footprints while a hazard holds focus: none. These are every
 *  *other* hazard's contours, rings and extents — the lines that have to go
 *  before the focused footprint reads as one shape. The focused hazard draws
 *  from its own source and is untouched by this. */
export function ambientFootprints(
  ambient: HazardFootprintCollection,
  focusActive: boolean,
): HazardFootprintCollection {
  return focusActive ? NO_FOOTPRINTS : ambient
}

/** A marker's opacity under focus. The focused hazard keeps whatever age and
 *  precision already gave it; everything else is scaled down. */
export function focusOpacity(
  base: number,
  focusActive: boolean,
  isFocused: boolean,
): number {
  if (!focusActive || isFocused) return base
  return base * FOCUS_DIM
}

/** Multiplier for layers painted by MapLibre rather than by React, where the
 *  opacity is an expression and focus can only scale the result. */
export function focusLayerOpacity(focusActive: boolean): number {
  return focusActive ? FOCUS_DIM : 1
}
