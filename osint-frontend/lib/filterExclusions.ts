// What the filters are currently keeping off the map, in words.
//
// Every control in the rail can hide events, and one of them — the severity
// range — can hide nearly all of them from a single stray click on its track,
// because clicking a two-thumb slider moves the nearest thumb to the click.
// The map then goes empty while the panel still looks perfectly normal: the
// only trace is a small "0.34 – 1.00" readout among a dozen other numbers.
//
// So the rail says what it is excluding and offers the way back. Pure
// functions: the wording is testable, and the rail only renders what these
// return.

export interface FilterSnapshot {
  sources: Record<string, boolean>
  hazardTypes: Record<string, boolean>
  severity: [number, number]
}

/** The full severity range — anything else is narrowing. */
export const FULL_SEVERITY: [number, number] = [0, 1]

export function severityIsNarrowed(severity: [number, number]): boolean {
  return severity[0] > FULL_SEVERITY[0] || severity[1] < FULL_SEVERITY[1]
}

function offCount(flags: Record<string, boolean>): number {
  return Object.values(flags).filter((on) => !on).length
}

/**
 * One short phrase per filter that is currently excluding something, in the
 * order they appear in the rail. Empty when nothing is being excluded.
 */
export function activeExclusions(filters: FilterSnapshot): string[] {
  const out: string[] = []
  const layersOff = offCount(filters.sources)
  if (layersOff > 0) out.push(`${layersOff} layer${layersOff === 1 ? "" : "s"} off`)
  const typesOff = offCount(filters.hazardTypes)
  if (typesOff > 0) out.push(`${typesOff} disaster type${typesOff === 1 ? "" : "s"} off`)
  if (severityIsNarrowed(filters.severity)) {
    out.push(`severity ${filters.severity[0].toFixed(2)}–${filters.severity[1].toFixed(2)}`)
  }
  return out
}

/**
 * Is the map showing less than everything it has, because someone asked it to?
 *
 * The map's own "no events match" overlay exists for the case that looks like
 * a fault — the window has events and none of them are on screen. Switching
 * every layer off produces that same emptiness on purpose, and an overlay
 * arguing with a deliberate choice is noise sitting on top of the map the
 * choice was meant to clear. The filter panel already says what is excluded
 * and offers the way back, so the map can stay quiet.
 */
export function filtersAreNarrowed(filters: FilterSnapshot): boolean {
  return activeExclusions(filters).length > 0
}

/**
 * The state worth shouting about: the window holds events and the filters are
 * showing none of them. Not an error — it is a legitimate thing to ask for —
 * but it must never be silent, because an empty map and a broken map look
 * exactly alike.
 */
export function filtersHideEverything(visibleCount: number, paneCount: number): boolean {
  return paneCount > 0 && visibleCount === 0
}
