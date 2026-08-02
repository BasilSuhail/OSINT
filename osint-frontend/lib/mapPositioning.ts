import type { VisibleEvent } from "./queries"

/** A news story, by category or by RSS source. */
export function isNews(ev: VisibleEvent): boolean {
  return ev.category === "news" || (ev.source ?? "").toLowerCase().startsWith("rss-")
}

/**
 * Where an event's marker goes, or null when it does not belong on the map.
 *
 * A news dot is a place. A story we cannot place gets no dot — it stays
 * reachable by clicking its country, which is what the side panel is for
 * (#717).
 *
 * News used to fall back to its country's centroid, which stacked every
 * unplaceable story from one country on a single point: 346 UK stories,
 * 474 US, one dot each. That is the #166 blob by another route. #166
 * suppressed it for "world" scope only, and that held while a story's
 * country and its coordinates both came from the same city match. Once a
 * story could take a country from the word "Britain" instead, "local"
 * rows started arriving with no coordinates and walked straight back into
 * the fallback.
 *
 * Hazards keep the fallback: a quake or cyclone with a country and no
 * point is still worth showing roughly, and there are few enough of them
 * that they do not stack.
 */
export function positionForEvent(
  ev: VisibleEvent,
  centroids: Map<string, [number, number]>,
): { lat: number; lon: number } | null {
  if (!hasPlaceLevelCoords(ev)) return null
  if (ev.lat != null && ev.lon != null) return { lat: ev.lat, lon: ev.lon }
  if (isNews(ev)) return null
  if (!ev.country) return null
  const c = centroids.get(ev.country)
  if (!c) return null
  return { lat: c[1], lon: c[0] }
}

export interface EventMarkerPosition {
  key: string
  lat: number
  lon: number
  place?: string
}

/** Expand one database story into every independently verified map point.
 *
 * The backend deliberately keeps one RSS row per article. Exact multi-place
 * evidence lives in `payload.place_locations`; this projection creates the
 * extra markers only at render time, so panels, counts, retention and refresh
 * identity never duplicate the story (#748).
 */
export function positionsForEvent(
  ev: VisibleEvent,
  centroids: Map<string, [number, number]>,
): EventMarkerPosition[] {
  const payload = (ev.payload ?? {}) as Record<string, unknown>
  const raw = payload.place_locations
  if (Array.isArray(raw)) {
    const positions: EventMarkerPosition[] = []
    const seen = new Set<string>()
    for (const value of raw) {
      if (!value || typeof value !== "object" || Array.isArray(value)) continue
      const location = value as Record<string, unknown>
      const id = typeof location.wikidata_id === "string" ? location.wikidata_id.trim() : ""
      const lat = location.lat
      const lon = location.lon
      if (
        !id ||
        seen.has(id) ||
        typeof lat !== "number" ||
        !Number.isFinite(lat) ||
        lat < -90 ||
        lat > 90 ||
        typeof lon !== "number" ||
        !Number.isFinite(lon) ||
        lon < -180 ||
        lon > 180
      ) {
        continue
      }
      seen.add(id)
      const label = typeof location.name === "string" ? location.name.trim() : ""
      positions.push({
        key: `${ev.id}:wikidata:${id}`,
        lat,
        lon,
        place: label ? label.toLowerCase() : undefined,
      })
    }
    if (positions.length > 0) return positions
  }
  const at = positionForEvent(ev, centroids)
  return at ? [{ key: String(ev.id), ...at }] : []
}

/**
 * Does this row's coordinate mean a place, or just a country?
 *
 * GDELT states how precisely it geocoded each event, and a country-level
 * row's lat/lon means "somewhere in Russia" — a real number that is not a
 * real place. Drawn as a pin it stacks with every other unplaceable event
 * from that country. Measured over three days: admin-level rows piled 21
 * deep on one point and country-level rows 10 deep, against 3.8 for
 * city-level. Those piles are the large circles on the map (#727).
 *
 * Only GDELT is filtered here. News carries no such flag and is already
 * held to the same standard by the resolver (#717). Hazards are coarse by
 * nature — an epicentre or a fire perimeter is not a town — and a handful
 * of them never stacks, so they are left alone.
 */
export function hasPlaceLevelCoords(ev: VisibleEvent): boolean {
  if ((ev.source ?? "").toLowerCase() !== "gdelt") return true
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const precision = typeof p.geo_precision === "string" ? p.geo_precision : null
  if (precision) return precision === "city"
  // Rows stored before the precision was recorded: ActionGeo_FullName is
  // "Tehran, Tehran, Iran" for a city and a bare "Iran" for a country.
  const name = typeof p.geo_name === "string" ? p.geo_name : p.country_fips
  if (typeof name !== "string" || !name) return false
  return name.split(",").filter((s) => s.trim()).length >= 3
}

/**
 * Which competing family a clusterable row belongs to, for budget sharing.
 *
 * Only used to keep one family from starving another — it is not a
 * category, and nothing downstream renders differently because of it.
 */
export function markerFamily(ev: VisibleEvent): string {
  const source = (ev.source ?? "").toLowerCase()
  if (source === "gdelt") return "gdelt"
  if (isNews(ev)) return "news"
  return source || "other"
}

/**
 * Share `budget` across families by round-robin, newest-first within each.
 *
 * The map caps total markers, and the rows competing for that cap arrive
 * ordered by `occurred_at` alone. That ordering is not neutral between
 * sources: news is minute-fresh, while GDELT publishes in daily batches
 * and so timestamps its newest row at midnight. Draining one flat
 * `occurred_at`-ordered list therefore let news take every slot and cut
 * GDELT to zero — 0 of 637 rows on a measured pull (#721).
 *
 * This is the same starvation the two-bucket split already fixed once for
 * hazards; it reappeared one level down between news and GDELT. Rather
 * than add a third special case, share what remains: take one row from
 * each family in turn, so a family's share degrades gradually with
 * pressure and no publishing cadence can zero another out. Families that
 * run short give their remainder back to the others automatically.
 */
export function shareBudget<T>(byFamily: Map<string, T[]>, budget: number): T[] {
  if (budget <= 0) return []
  const queues = [...byFamily.values()].filter((q) => q.length > 0)
  if (queues.length === 0) return []
  const out: T[] = []
  let cursor = 0
  // Stop when the budget is spent or every queue is drained.
  while (out.length < budget) {
    let drewAny = false
    for (const queue of queues) {
      if (out.length >= budget) break
      if (cursor < queue.length) {
        out.push(queue[cursor])
        drewAny = true
      }
    }
    if (!drewAny) break
    cursor += 1
  }
  return out
}

/** West/south/east/north in degrees, as MapLibre reports them. */
export interface MapBounds {
  west: number
  south: number
  east: number
  north: number
}

/**
 * Grow a viewport by a fraction of its own size.
 *
 * The budget is spent on what is inside the box, so a marker just outside
 * it does not exist yet. Without a margin those markers appear the instant
 * they cross the edge during a pan, which reads as flicker. A margin means
 * the map has already drawn what is just off-screen.
 */
export function padBounds(bounds: MapBounds, fraction = 0.25): MapBounds {
  const dLat = (bounds.north - bounds.south) * fraction
  const spanLon = bounds.east - bounds.west
  const dLon = (spanLon >= 0 ? spanLon : spanLon + 360) * fraction
  return {
    south: Math.max(-90, bounds.south - dLat),
    north: Math.min(90, bounds.north + dLat),
    west: bounds.west - dLon,
    east: bounds.east + dLon,
  }
}

/**
 * Is this point inside the viewport?
 *
 * Handles a box that crosses the antimeridian, where MapLibre reports a
 * west greater than its east (say 170 to -170); the longitude test then
 * has to be an "or" rather than an "and". Once the padded box spans 360
 * degrees or more, everything is in view and the test is skipped — which
 * is the world view, where a viewport filter has nothing to do.
 */
export function withinBounds(lat: number, lon: number, bounds: MapBounds): boolean {
  if (lat < bounds.south || lat > bounds.north) return false
  const span = bounds.east - bounds.west
  if (span >= 360 || span <= -360) return true
  const west = ((bounds.west + 180) % 360 + 360) % 360 - 180
  const east = ((bounds.east + 180) % 360 + 360) % 360 - 180
  const x = ((lon + 180) % 360 + 360) % 360 - 180
  return west <= east ? x >= west && x <= east : x >= west || x <= east
}

/** A point with whatever payload the caller is grouping. */
export interface Located {
  lat: number
  lon: number
  /** Optional marker-specific name when one story owns several points. */
  place?: string | null
}

/** The place a row claims to be, lowercased, or null if it names none. */
export function placeName(ev: VisibleEvent): string | null {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  // GDELT: "Tehran, Tehran, Iran" — the settlement is the first part.
  const geo = typeof p.geo_name === "string" ? p.geo_name.split(",")[0] : null
  const city = typeof p.city === "string" ? p.city : null
  const name = (geo || city || "").trim().toLowerCase()
  return name || null
}

/** Kilometres between two points. Equirectangular — exact enough under a
 *  few hundred km, which is all this is asked to judge. */
export function approxKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const dLat = bLat - aLat
  const dLon = (bLon - aLon) * Math.cos(((aLat + bLat) / 2) * (Math.PI / 180))
  return Math.hypot(dLat, dLon) * 111.19
}

/**
 * Merge marks that are the same named place, sitting close together.
 *
 * GDELT ships its own coordinate per event; news rows take theirs from
 * the bundled gazetteer. The two never agree exactly, so every city both
 * sources cover drew as a pair of overlapping circles — London 250 m
 * apart, and the same for Kyiv, Moscow, Delhi, Tehran and every other
 * busy city (#735).
 *
 * Both tests are needed, and neither alone is safe:
 *
 *   London / Twickenham   different names, 20 km apart — stay separate.
 *                         A radius wide enough to merge London's own
 *                         spread would have swallowed Twickenham too.
 *   Springfield x3        same name, different states — stay separate.
 *                         There are many Springfields.
 *   London / London       same name, 250 m apart — one mark.
 *
 * Rows naming no place are never merged: without a name there is no
 * evidence they are the same place, and guessing from distance alone is
 * how distinct neighbourhoods get collapsed.
 */
export function mergeSamePlace<T extends Located & { ev: VisibleEvent }>(
  items: T[],
  toleranceKm = 25,
): T[][] {
  const groups: { name: string; lat: number; lon: number; members: T[] }[] = []
  const out: T[][] = []
  for (const item of items) {
    const name = item.place ?? placeName(item.ev)
    if (!name) {
      out.push([item])
      continue
    }
    const hit = groups.find(
      (g) => g.name === name && approxKm(g.lat, g.lon, item.lat, item.lon) <= toleranceKm,
    )
    if (hit) hit.members.push(item)
    else groups.push({ name, lat: item.lat, lon: item.lon, members: [item] })
  }
  return out.concat(groups.map((g) => g.members))
}
