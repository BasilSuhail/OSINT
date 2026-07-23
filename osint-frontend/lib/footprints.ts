// Synthesized hazard footprints — drawn from the point data we already store
// (magnitude, depth, burned-area text). These are VISUAL APPROXIMATIONS of the
// GDACS/USGS products, not the official ShakeMap / burn geometry. Pure functions,
// no map dependency, so they're trivially unit-testable.

const KM_PER_DEG_LAT = 110.574

/** Closed polygon ring approximating a circle of `radiusKm` around (lon,lat).
 *  Equirectangular small-angle projection — accurate enough at event scale. */
export function circlePolygon(
  lon: number,
  lat: number,
  radiusKm: number,
  steps = 64,
): [number, number][] {
  const kmPerDegLon = 111.32 * Math.cos((lat * Math.PI) / 180)
  const ring: [number, number][] = []
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI
    const dLon = (radiusKm / kmPerDegLon) * Math.cos(a)
    const dLat = (radiusKm / KM_PER_DEG_LAT) * Math.sin(a)
    ring.push([lon + dLon, lat + dLat])
  }
  ring[ring.length - 1] = ring[0] // exact closure
  return ring
}

/** Surface radius (km) at which modified-Mercalli intensity `mmi` is felt for a
 *  quake of moment magnitude `magnitude` at `depthKm`. Simplified intensity-
 *  prediction inversion: epicentral intensity ~1.5M, log-distance decay, then
 *  projected from hypocentral to surface distance. Approximation, not seismology. */
export function feltRadiusKm(magnitude: number, depthKm: number, mmi: number): number {
  const epicentralIntensity = 1.5 * magnitude - 1.0
  if (mmi >= epicentralIntensity) return 0
  const rHypo = Math.pow(10, (epicentralIntensity - mmi) / 2.0)
  const rSurfSq = rHypo * rHypo - depthKm * depthKm
  return rSurfSq > 0 ? Math.sqrt(rSurfSq) : 0
}

/** Hectares from GDACS `severity_raw` free text (e.g. "... in 8028 ha"). */
export function parseBurnedHa(severityRaw: string | null | undefined): number | null {
  if (!severityRaw) return null
  const m = severityRaw.match(/([\d.,]+)\s*ha\b/i)
  if (!m) return null
  const n = Number(m[1].replace(/,/g, ""))
  return Number.isFinite(n) ? n : null
}

/** Radius (km) of a circle whose area equals `areaHa` hectares (1 ha = 0.01 km²). */
export function fireRadiusKm(areaHa: number): number {
  return Math.sqrt((areaHa * 0.01) / Math.PI)
}

// EONET reports an event's size as a structured magnitude rather than GDACS'
// free text — wildfires in acres, sea ice in square nautical miles. Hectares
// per unit, so the existing radius maths is reused unchanged.
const HA_PER_AREA_UNIT: Record<string, number> = {
  acres: 0.404686,
  acre: 0.404686,
  "nm^2": 342.99,
  km2: 100,
  "km^2": 100,
  ha: 1,
}

/** Hectares from an EONET `magnitude_value` + `magnitude_unit` pair. Null when
 *  the unit is not an area (storms report knots) or the value is unusable. */
export function magnitudeAreaHa(
  value: number | null | undefined,
  unit: string | null | undefined,
): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null
  const factor = HA_PER_AREA_UNIT[String(unit ?? "").toLowerCase()]
  return factor ? value * factor : null
}

export type FootprintBand = { mmi: number; color: string; radiusKm: number }

// MMI band → ring colour (felt → destructive), green to red.
const MMI_BANDS: { mmi: number; color: string }[] = [
  { mmi: 4, color: "#22c55e" },
  { mmi: 5, color: "#eab308" },
  { mmi: 6, color: "#f97316" },
  { mmi: 7, color: "#ef4444" },
]

/** Concentric intensity bands for a quake, largest (weakest) first, dropping any
 *  band whose surface radius collapses to 0. */
export function quakeBands(magnitude: number, depthKm: number): FootprintBand[] {
  return MMI_BANDS.map(({ mmi, color }) => ({
    mmi,
    color,
    radiusKm: feltRadiusKm(magnitude, depthKm, mmi),
  })).filter((b) => b.radiusKm > 0)
}
