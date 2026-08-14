/** Live aircraft, and the rules about when they may be shown (#873). */

/** What an airframe is for, read from its type designator by the backend. */
export type AircraftRole =
  | "tanker"
  | "isr"
  | "fighter"
  | "transport"
  | "rotorcraft"
  | "trainer"
  | "other"

/** Why an aircraft is on the operator's list. The label says what it is *for* —
 *  an office, a fleet, a job — and never who is aboard. */
export interface AircraftWatch {
  label: string
  category: "state" | "vip" | "other"
}

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
  kind: "military" | "distress" | "watched"
  role: AircraftRole
  /** The aggregator's own database flag, bit 1 meaning military in its
   *  scheme. Its claim about an airframe, not a reading of anything the
   *  aircraft transmitted. */
  source_flags?: number | null
  watch: AircraftWatch | null
  /** When this console first saw it flying, not when it took off. Only ever
   *  set for a watched aircraft. */
  airborne_since: string | null
}

export interface PresenceAnswer {
  fetched_at: string
  count: number
  /** How many airframes are on the operator's list — not how many are flying.
   *  Both numbers are needed to explain an empty layer: nobody watching and
   *  nothing airborne look identical on a map and are not the same thing. */
  watching?: number
  aircraft: PresenceAircraft[]
  degraded: boolean
}

/**
 * The three marks the air layer draws, in one place (#954).
 *
 * Here rather than in the components because the rail is the map's legend for
 * this layer, and a legend that keeps its own copy of a colour is a legend
 * that will eventually be wrong. The map and the switch read the same
 * constant, so they cannot disagree.
 *
 * Amber for watched, not red: red is spent on the emergency, and an aircraft
 * somebody is following is not an emergency. Sky for routine traffic, because
 * it is the quietest of the three and there is the most of it.
 */
export const AIRCRAFT_COLORS = {
  military: "#7dd3fc",
  watched: "#fcd34d",
  distress: "#ef4444",
} as const

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
/** The role in words. `other` prints nothing: a designator the backend has
 *  never been taught is not a transport, and naming it one would put a fact on
 *  a card that nothing measured. */
export function roleLabel(role: AircraftRole): string | null {
  switch (role) {
    case "tanker":
      return "tanker"
    case "isr":
      return "surveillance"
    case "fighter":
      return "fighter"
    case "transport":
      return "transport"
    case "rotorcraft":
      return "rotorcraft"
    case "trainer":
      return "trainer"
    default:
      return null
  }
}

/**
 * How long this console has had eyes on a watched aircraft.
 *
 * Deliberately not "airborne for": the console knows when it first saw the
 * aircraft flying, which is the same thing only if it was watching when the
 * wheels left the ground. The wording has to survive a reader who started the
 * console ten minutes ago.
 */
export function airborneLabel(airborneSince: string | null, nowMs: number): string | null {
  if (!airborneSince) return null
  const started = Date.parse(airborneSince)
  if (Number.isNaN(started)) return null
  const minutes = Math.max(0, Math.round((nowMs - started) / 60_000))
  if (minutes < 1) return "seen flying just now"
  if (minutes < 60) return `seen flying for ${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `seen flying for ${hours}h` : `seen flying for ${hours}h ${rest}m`
}

export function aircraftFacts(a: PresenceAircraft): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = []
  const type = a.type?.trim()
  if (type) out.push({ label: "type", value: type })
  const role = roleLabel(a.role)
  if (role) out.push({ label: "role", value: role })
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

/**
 * Why the watchlist layer is drawing nothing, in words, or null when it is
 * drawing something.
 *
 * A switch that is on and shows nothing reads as broken. It is usually not
 * broken — it is either unconfigured or the watched aircraft are on the
 * ground — and those are different enough that the reader has to be told
 * which.
 */
/**
 * What the card calls an aircraft that is on the feed's military list.
 *
 * "Military" flat is a claim this console never checked. The list is the
 * aggregator's database flag, and it covers government and head-of-state
 * transports as well as air forces — a wide-body airliner on it is the flag
 * working, not the layer failing. So the card attributes it.
 */
export function militaryLabel(): string {
  return "flagged military by the feed"
}

export function watchlistHint(watching: number, drawn: number): string | null {
  if (drawn > 0) return null
  if (watching === 0) return "none watched — add data/watchlist.json"
  return watching === 1 ? "1 watched · none airborne" : `${watching} watched · none airborne`
}
