/** Vessels broadcasting AIS, live and unstored (#954).
 *
 * The category is transmitted, not inferred: AIS carries a ship type in the
 * static message every vessel sends, so "fishing" and "tankers" are separate
 * switches without a model or a guess behind them.
 *
 * Coverage is one authority's terrestrial receivers. This layer covers a sea
 * area, not an ocean, and the rail says so — an empty Atlantic on this map is
 * an empty receiver map.
 */

export type VesselCategory =
  | "cargo"
  | "tanker"
  | "passenger"
  | "fishing"
  | "pleasure"
  | "service"
  | "other"

export interface PresenceVessel {
  mmsi: number | null
  name: string | null
  callsign: string | null
  imo: number | null
  lat: number
  lon: number
  speed_kt: number | null
  /** Course over the ground. Null when the vessel sent the "not available"
   *  code, which must never be drawn as a direction. */
  course: number | null
  heading: number | null
  nav_status: string | null
  category: VesselCategory
  ship_type: number | null
  destination: string | null
  /** Whether the vessel said its own fix was accurate. */
  position_accurate: boolean | null
  /** Why this position is not believed, or null. `speed` — a speed no ship
   *  reaches. `stacked` — several moving hulls on one point. Both are the
   *  fingerprint of interference rather than of a vessel. */
  position_suspect: "speed" | "stacked" | null
  reported_at: string | null
}

export interface VesselAnswer {
  fetched_at: string
  count: number
  /** Attribution for every feed that answered this refresh. Rendered rather
   *  than hardcoded: the layer can cover more than one sea area, each with its
   *  own licence and its own notice to carry, and a console that names a
   *  source it did not use is as wrong as one that names none. */
  sources?: string[]
  vessels: PresenceVessel[]
  degraded: boolean
}

/** The notice to print under the layer. Falls back to nothing rather than to a
 *  guess: an unattributed feed is a licence problem, and inventing the line
 *  would hide it. */
export function vesselAttribution(sources: string[] | undefined): string | null {
  const named = (sources ?? []).filter((s) => s.trim())
  return named.length > 0 ? named.join(" · ") : null
}

/** Slower than the aircraft poll: a ship under way covers a few hundred metres
 *  in a minute, and asking faster is not more truthful, only more expensive for
 *  a public authority's server. */
export const VESSEL_POLL_MS = 45_000

/** The rail rows, in the order a reader looks for them. Ordered by how much of
 *  the water they are: trade first, then the boats that serve it. */
export const VESSEL_CATEGORIES: { key: VesselCategory; label: string; hint: string }[] = [
  { key: "cargo", label: "Cargo", hint: "freight and container traffic" },
  { key: "tanker", label: "Tankers", hint: "oil, chemical and gas carriers" },
  { key: "passenger", label: "Passenger", hint: "ferries, cruise and high-speed craft" },
  { key: "fishing", label: "Fishing", hint: "vessels declaring themselves fishing" },
  { key: "pleasure", label: "Pleasure", hint: "sailing and private craft" },
  { key: "service", label: "Service", hint: "tugs, pilots, rescue, dredgers" },
  { key: "other", label: "Unclassified", hint: "no type transmitted" },
]

/**
 * What is wrong with a position, in words a reader can act on.
 *
 * The mark is drawn either way. A transmitter claiming to be a ship in the
 * middle of a forest is a real thing that is really happening and is worth
 * more than the traffic around it — but it must not be drawn as an ordinary
 * vessel, so it says which test it failed.
 */
export function suspectReason(v: PresenceVessel): string | null {
  switch (v.position_suspect) {
    case "speed":
      return "reported speed no vessel can reach"
    case "stacked":
      return "several moving vessels on one position"
    default:
      return null
  }
}

/** The name a listener would hear first, falling back the way AIS degrades:
 *  the ship's name, then its call sign, then the number its transponder always
 *  sends. */
export function vesselTitle(v: PresenceVessel): string {
  const name = v.name?.trim()
  if (name) return name
  const callsign = v.callsign?.trim()
  if (callsign) return callsign
  if (v.mmsi != null) return `MMSI ${v.mmsi}`
  return "Unknown vessel"
}

/**
 * Whether the mark should point anywhere.
 *
 * Heading is what the hull is pointing at and course is where it is going;
 * they differ in a current, and heading is the truer one for drawing a hull.
 * A vessel that sent neither is drawn unrotated, because north would be a
 * direction it never claimed.
 */
export function vesselBearing(v: PresenceVessel): number | null {
  if (v.heading != null) return v.heading
  if (v.course != null) return v.course
  return null
}

/** Whether a vessel is going anywhere. Below half a knot is noise in a moored
 *  ship's own position, not movement, and drawing it as under way would put a
 *  wake on a hull that has been tied up for a week. */
export function vesselIsUnderWay(v: PresenceVessel): boolean {
  if (v.nav_status === "at anchor" || v.nav_status === "moored" || v.nav_status === "aground") {
    return false
  }
  return (v.speed_kt ?? 0) >= 0.5
}

/**
 * What the vessel is currently transmitting, as label/value lines.
 *
 * Absent fields are left out rather than rendered blank, the same rule the
 * aircraft card follows: an empty value reads as a measurement of nothing when
 * what happened is that nothing was measured.
 */
export function vesselFacts(v: PresenceVessel): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = []
  const category = VESSEL_CATEGORIES.find((c) => c.key === v.category)
  if (category && v.category !== "other") out.push({ label: "type", value: category.label })
  if (v.nav_status) out.push({ label: "status", value: v.nav_status })
  if (v.speed_kt != null) {
    out.push({
      label: "speed",
      value: v.speed_kt < 0.5 ? "stopped" : `${v.speed_kt.toFixed(1)} kt`,
    })
  }
  const bearing = vesselBearing(v)
  if (bearing != null) out.push({ label: "heading", value: `${Math.round(bearing)}°` })
  const destination = v.destination?.trim()
  //: What the crew typed, and nothing more. It is a free-text field on a form,
  //: it is often stale and sometimes a joke, and the card says whose claim it
  //: is rather than presenting it as a fact about where the ship will go.
  if (destination) out.push({ label: "says bound for", value: destination })
  const callsign = v.callsign?.trim()
  if (callsign) out.push({ label: "call sign", value: callsign })
  if (v.imo != null) out.push({ label: "IMO", value: String(v.imo) })
  if (v.mmsi != null) out.push({ label: "MMSI", value: String(v.mmsi) })
  return out
}
