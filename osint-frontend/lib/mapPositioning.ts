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
  if (ev.lat != null && ev.lon != null) return { lat: ev.lat, lon: ev.lon }
  if (isNews(ev)) return null
  if (!ev.country) return null
  const c = centroids.get(ev.country)
  if (!c) return null
  return { lat: c[1], lon: c[0] }
}
