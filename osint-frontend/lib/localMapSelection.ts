const EARTH_RADIUS_KM = 6_371
const MIN_LOCAL_RADIUS_KM = 0.15
const MAX_LOCAL_RADIUS_KM = 50

interface RenderedFeatureLike {
  layer?: { id?: string }
  properties?: Record<string, unknown> | null
}

export interface LocalMapLabel {
  name: string
  kind: "street" | "neighbourhood" | "village" | "town" | "city" | "place" | "water"
}

export type LocalAreaKind = LocalMapLabel["kind"] | "coordinate"

export interface LocalPosition<TEvent, TLocation = unknown> {
  ev: TEvent
  lat: number
  lon: number
  location?: TLocation
}

export interface LocalEventSelection<TEvent, TLocation = unknown> {
  event: TEvent
  location?: TLocation
  distanceKm: number
}

export interface LocalSelectionBounds {
  west: number
  south: number
  east: number
  north: number
}

const LABEL_LAYERS: Array<{
  test: (layerId: string) => boolean
  kind: LocalMapLabel["kind"]
}> = [
  { test: (id) => id === "building", kind: "place" },
  { test: (id) => id.startsWith("highway_name"), kind: "street" },
  { test: (id) => id === "place_suburb", kind: "neighbourhood" },
  { test: (id) => id === "landuse_park", kind: "place" },
  { test: (id) => ["place_other", "place_village"].includes(id), kind: "village" },
  { test: (id) => id === "place_town", kind: "town" },
  { test: (id) => ["place_city", "place_city_large"].includes(id), kind: "city" },
  { test: (id) => id === "water_name", kind: "water" },
]

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

/** The most specific visible OpenFreeMap label under a click.
 * Country/state labels are deliberately excluded: map clicks are local-only
 * and country navigation belongs to an explicit search/list action (#774). */
export function localMapLabel(features: RenderedFeatureLike[]): LocalMapLabel | null {
  for (const candidate of LABEL_LAYERS) {
    for (const feature of features) {
      const layerId = feature.layer?.id ?? ""
      if (!candidate.test(layerId)) continue
      const p = feature.properties ?? {}
      const name =
        text(p.name_en) ??
        text(p["name:latin"]) ??
        text(p.name) ??
        text(p.ref)
      if (name) return { name, kind: candidate.kind }
    }
  }
  return null
}

/** Geographic radius represented by a detailed map click.
 * It halves with every zoom level and never grows beyond a city-scale 50 km
 * or shrinks below a walkable building/street-scale 150 m. */
export function localSelectionRadiusKm(
  zoom: number,
  kind: LocalAreaKind = "coordinate",
): number {
  const raw = 12_800 / 2 ** Math.max(0, zoom)
  const kindMaximum: Record<LocalAreaKind, number> = {
    place: 0.5,
    street: 0.75,
    neighbourhood: 5,
    village: 3,
    town: 8,
    city: 15,
    water: 10,
    coordinate: MAX_LOCAL_RADIUS_KM,
  }
  const clamped = Math.min(
    MAX_LOCAL_RADIUS_KM,
    kindMaximum[kind],
    Math.max(MIN_LOCAL_RADIUS_KM, raw),
  )
  if (clamped >= 10) return Math.round(clamped)
  if (clamped >= 1) return Number(clamped.toFixed(1))
  return Number(clamped.toFixed(2))
}

export function distanceKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const radians = Math.PI / 180
  const dLat = (bLat - aLat) * radians
  const dLon = (bLon - aLon) * radians
  const lat1 = aLat * radians
  const lat2 = bLat * radians
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)))
}

function normalizeLongitude(value: number): number {
  return ((value + 180) % 360 + 360) % 360 - 180
}

/** Bounding box that fully encloses a local selection circle.
 * A west value greater than east intentionally represents antimeridian wrap. */
export function localSelectionBounds(
  lat: number,
  lon: number,
  radiusKm: number,
): LocalSelectionBounds {
  const latDelta = radiusKm / 110.574
  const kmPerDegreeLon = 111.32 * Math.max(0.01, Math.cos((lat * Math.PI) / 180))
  const lonDelta = Math.min(180, radiusKm / kmPerDegreeLon)
  return {
    west: normalizeLongitude(lon - lonDelta),
    south: Math.max(-90, lat - latDelta),
    east: normalizeLongitude(lon + lonDelta),
    north: Math.min(90, lat + latDelta),
  }
}

/** Select each story once, using its nearest verified position to the click. */
export function localEventSelections<
  TEvent extends { id: string | number; occurred_at: string },
  TLocation = unknown,
>(
  positions: LocalPosition<TEvent, TLocation>[],
  lat: number,
  lon: number,
  radiusKm: number,
): LocalEventSelection<TEvent, TLocation>[] {
  const nearest = new Map<string | number, LocalEventSelection<TEvent, TLocation>>()
  for (const position of positions) {
    const distance = distanceKm(lat, lon, position.lat, position.lon)
    if (distance > radiusKm) continue
    const existing = nearest.get(position.ev.id)
    if (!existing || distance < existing.distanceKm) {
      nearest.set(position.ev.id, {
        event: position.ev,
        location: position.location,
        distanceKm: distance,
      })
    }
  }

  return [...nearest.values()].sort((a, b) => {
    const distanceOrder = a.distanceKm - b.distanceKm
    if (Math.abs(distanceOrder) > 0.01) return distanceOrder
    return Date.parse(b.event.occurred_at) - Date.parse(a.event.occurred_at)
  })
}

export function coordinateLabel(lat: number, lon: number): string {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`
}
