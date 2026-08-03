import type { EventRow } from "./types"

function revisionStamp(event: EventRow): string | null {
  return event.updated_at ?? event.fetched_at ?? null
}

/** Merge a complete viewport snapshot without rolling a newer live/enriched
 * buffer row back to older coordinates or provenance. */
export function mergeEventRows(base: EventRow[], supplemental: EventRow[]): EventRow[] {
  const merged = new Map(base.map((event) => [event.id, event]))
  for (const event of supplemental) {
    const current = merged.get(event.id)
    if (!current) {
      merged.set(event.id, event)
      continue
    }
    const incomingStamp = revisionStamp(event)
    const currentStamp = revisionStamp(current)
    if (!incomingStamp) continue
    if (!currentStamp) {
      merged.set(event.id, event)
      continue
    }
    const incomingMs = new Date(incomingStamp).getTime()
    const currentMs = new Date(currentStamp).getTime()
    if (!Number.isFinite(incomingMs)) continue
    if (!Number.isFinite(currentMs)) {
      merged.set(event.id, event)
      continue
    }
    if (
      incomingMs > currentMs ||
      (incomingMs === currentMs && incomingStamp > currentStamp)
    ) {
      merged.set(event.id, event)
    }
  }
  return [...merged.values()]
}
