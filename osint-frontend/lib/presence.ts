/** Live aircraft, and the rules about when they may be shown (#873). */

export interface PresenceAircraft {
  hex: string | null
  callsign: string | null
  type: string | null
  registration: string | null
  lat: number
  lon: number
  track: number | null
  alt_ft: number | null
  speed_kt: number | null
  squawk: string | null
  kind: "military" | "distress"
}

export interface PresenceAnswer {
  fetched_at: string
  count: number
  aircraft: PresenceAircraft[]
  degraded: boolean
}

/** How often the map asks. Positions go stale in seconds; asking faster is not
 *  more truthful, only more expensive for somebody else's server. */
export const PRESENCE_POLL_MS = 30_000

/** Anything older than this is not "now" (#873).
 *
 * Nothing about presence is stored, so there is no past to show. A live layer
 * left visible over a map scrubbed back three weeks would be the most
 * convincing lie this console could tell — the dots would look like history.
 */
const NOW_TOLERANCE_MS = 5 * 60_000

export function windowIsNow(windowEndOffsetMs: number): boolean {
  return windowEndOffsetMs <= NOW_TOLERANCE_MS
}

/** Whether to be asking at all: switched on, at "now", and actually visible.
 *  A background tab must not spend a free service's bandwidth. */
export function shouldPoll(
  enabled: boolean,
  windowEndOffsetMs: number,
  documentVisible: boolean,
): boolean {
  return enabled && documentVisible && windowIsNow(windowEndOffsetMs)
}

/** "as of 8s ago" — a live layer that will not say when it last heard
 *  anything is indistinguishable from a frozen one. */
export function ageLabel(fetchedAt: string, nowMs: number): string {
  const seconds = Math.max(0, Math.round((nowMs - Date.parse(fetchedAt)) / 1000))
  if (seconds < 60) return `as of ${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  return `as of ${minutes}m ago`
}
