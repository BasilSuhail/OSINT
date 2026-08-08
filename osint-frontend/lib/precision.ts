import type { EventRow, LocationPrecision } from "./types"

/** What a coordinate is claiming, defaulting to the honest answer.
 *
 * An older API, or a row cached before #773, carries no verdict. "unknown" is
 * the right default there: a marker that cannot say how precise it is must not
 * imply that it is precise. */
export function precisionOf(ev: EventRow): LocationPrecision {
  return ev.location_precision ?? "unknown"
}

/** How the reader is told, in words rather than a jargon token. */
export const PRECISION_LABEL: Record<LocationPrecision, string> = {
  exact: "verified location",
  city: "somewhere in this city",
  area: "somewhere in this area",
  country: "somewhere in this country",
  unknown: "location not established",
}

/** Marker size in pixels.
 *
 * A vaguer claim is drawn wider, never tighter. The numbers are screen-space
 * rather than a projection of the metre radius on purpose: at low zoom a
 * country radius would swallow the map, and the point of the distinction is
 * that a reader can see it at the zoom they are actually at. */
export const PRECISION_RADIUS_PX: Record<LocationPrecision, number> = {
  exact: 4,
  city: 7,
  area: 9,
  country: 11,
  unknown: 5,
}

/** Fill opacity. An exact point is solid; a claim about an area is not, so it
 *  reads as a region rather than as a pin somebody surveyed. */
export const PRECISION_OPACITY: Record<LocationPrecision, number> = {
  exact: 1,
  city: 0.45,
  area: 0.3,
  country: 0.25,
  unknown: 0.4,
}
