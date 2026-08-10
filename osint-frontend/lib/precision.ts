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

/** Marker size in pixels: one size, whatever the coordinate claims (#891).
 *
 * Sizing a lone point by vagueness made the least informative marks the
 * largest ones on the map — a country-precision story drew wider than a
 * two-event cluster — and fading them by vagueness on top of the age fade
 * multiplied to nearly nothing, so the fill vanished and left a bright empty
 * ring that read as data still loading.
 *
 * Precision is still said, in the only place that can say it without
 * inflating anything: the words in the side panel, and `location_precision`
 * with `location_radius_m` on the API row. */
export const MARKER_RADIUS_PX = 4
