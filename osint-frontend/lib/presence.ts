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

/** The name a listener would hear first, falling back the way the transponder
 *  degrades: callsign, then registration, then the ICAO hex it always sends. */
export function aircraftTitle(a: PresenceAircraft): string {
  const callsign = a.callsign?.trim()
  if (callsign) return callsign
  const registration = a.registration?.trim()
  if (registration) return registration
  const hex = a.hex?.trim()
  if (hex) return hex.toUpperCase()
  return "Unknown aircraft"
}

/**
 * What the aircraft is currently transmitting, as label/value lines.
 *
 * Fields the transponder never sent are left out rather than rendered blank: an
 * empty value reads as a measurement of nothing, when what happened is that
 * nothing was measured. Zero feet is a real reading and says so in words,
 * because "0 ft" beside a moving aircraft looks like a missing number.
 */
export function aircraftFacts(a: PresenceAircraft): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = []
  const type = a.type?.trim()
  if (type) out.push({ label: "type", value: type })
  const registration = a.registration?.trim()
  if (registration) out.push({ label: "registration", value: registration })
  if (a.alt_ft != null) {
    out.push({
      label: "altitude",
      value: a.alt_ft <= 0 ? "on the ground" : `${Math.round(a.alt_ft).toLocaleString()} ft`,
    })
  }
  if (a.speed_kt != null) out.push({ label: "speed", value: `${Math.round(a.speed_kt)} kt` })
  if (a.track != null) out.push({ label: "track", value: `${Math.round(a.track)}°` })
  const squawk = a.squawk?.trim()
  if (squawk) out.push({ label: "squawk", value: squawk })
  const hex = a.hex?.trim()
  if (hex) out.push({ label: "hex", value: hex.toUpperCase() })
  return out
}
