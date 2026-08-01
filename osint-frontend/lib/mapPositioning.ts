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
