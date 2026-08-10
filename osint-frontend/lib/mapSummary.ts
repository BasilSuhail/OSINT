// What is on the map right now, counted by kind.
//
// The filter panel used to open on a header that counted the *buffer* — how
// many events had been fetched — which is not a question anyone looking at a
// map has. The question is what is on the map at this moment, and of what.
//
// Counts are taken from the events that survived every filter, so the header
// and the markers can never disagree: they are the same list.

import { hazardKind } from "./hazardSymbols"
import { HAZARD_TYPE_FILTERS, SOURCE_FILTERS, sourceKeyForEvent, type EventRow } from "./types"

export interface SummaryChip {
  key: string
  label: string
  hex: string
  count: number
}

/** Hazards are counted by disaster type; everything else by its source. */
function chipFor(ev: EventRow): { key: string; label: string; hex: string } | null {
  if (ev.category === "hazard") {
    const kind = hazardKind(ev)
    const filter = HAZARD_TYPE_FILTERS.find((h) => h.key === kind)
    if (filter) return { key: filter.key, label: filter.label, hex: filter.hex }
    //: An unrecognised hazard is still on the map, so it is still counted —
    //: under its source, which is the only honest label left for it.
  }
  const source = sourceKeyForEvent(ev)
  if (!source) return null
  const filter = SOURCE_FILTERS.find((f) => f.key === source)
  return filter ? { key: filter.key, label: filter.label, hex: filter.hex } : null
}

/**
 * One chip per kind present on the map, largest first, ties alphabetical.
 *
 * Kinds with nothing on the map are absent rather than shown as zero: a row of
 * zeros describes the filter list, which is directly below, and buries the two
 * or three counts that actually say what is being looked at.
 */
export function mapSummary(visible: EventRow[]): SummaryChip[] {
  const counts = new Map<string, SummaryChip>()
  for (const ev of visible) {
    const chip = chipFor(ev)
    if (!chip) continue
    const seen = counts.get(chip.key)
    if (seen) seen.count += 1
    else counts.set(chip.key, { ...chip, count: 1 })
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}
