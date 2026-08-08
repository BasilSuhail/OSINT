import { precisionOf } from "./precision"
import type { LocationPrecision } from "./types"
import type { MarkerLocationContext } from "./locationProvenance"
import type { VisibleEvent } from "./queries"
import { colorForEvent } from "./types"

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
  location?: MarkerLocationContext
}

export interface PositionedMapEvent extends Omit<EventMarkerPosition, "key"> {
  ev: VisibleEvent
  markerKey: string
}

export interface EventPointCollection {
  type: "FeatureCollection"
  features: Array<{
    type: "Feature"
    id: string
    properties: {
      markerKey: string
      color: string
      opacity: number
      /** How big this coordinate's claim is (#773), so the renderer can draw
       *  a city centroid as an area rather than as a surveyed point. */
      precision: LocationPrecision
    }
    geometry: {
      type: "Point"
      coordinates: [number, number]
    }
  }>
}

/**
 * Convert every place-backed event position into a MapLibre source feature.
 *
 * Density is a renderer concern: the GeoJSON source clusters these features
 * on the map worker, but no valid position is sampled or discarded before it
 * reaches that worker. Feature properties stay deliberately small; the full
 * event and marker-specific provenance remain in the caller's lookup map.
 */
export function eventPointCollection(items: PositionedMapEvent[]): EventPointCollection {
  return {
    type: "FeatureCollection",
    features: items.map((item) => ({
      type: "Feature",
      id: item.markerKey,
      properties: {
        markerKey: item.markerKey,
        color: colorForEvent(item.ev),
        opacity: item.ev.opacity,
        precision: precisionOf(item.ev),
      },
      geometry: {
        type: "Point",
        coordinates: [item.lon, item.lat],
      },
    })),
  }
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
        location: {
          lat,
          lon,
          name: label || null,
          precision: typeof location.precision === "string" ? location.precision : null,
          source: "wikidata",
          wikidataId: id,
          description:
            typeof location.description === "string" ? location.description : null,
          checkedAt: typeof location.checked_at === "string" ? location.checked_at : null,
          model: typeof location.model === "string" ? location.model : null,
        },
      })
    }
    if (positions.length > 0) return positions
  }
  const at = positionForEvent(ev, centroids)
  if (!at) return []
  const usedCountryFallback = ev.lat == null || ev.lon == null
  return [
    {
      key: String(ev.id),
      ...at,
      location: usedCountryFallback
        ? {
            ...at,
            name: ev.country,
            precision: "unknown",
            source: "country-centroid",
          }
        : undefined,
    },
  ]
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
