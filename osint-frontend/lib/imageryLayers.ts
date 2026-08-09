/** Satellite imagery drawn under the markers (#875).
 *
 * Raster tiles straight from the publisher to the browser. Nothing is fetched
 * by the API, nothing is stored, no row is written, and no retention window is
 * involved — which is why this is worth having at all.
 *
 * Both layers are addressed by day, and they follow the time scrubber rather
 * than pinning to today. A console whose map says three weeks ago while its
 * backdrop shows last night would be worse than having no backdrop: the reader
 * has no way to tell the two timescales apart once they disagree.
 *
 * Measured against the live endpoint: the archive goes back years, but
 * individual days are genuinely missing — 2026-08-06 and 2026-07-15 both
 * return 404 for tiles that exist on either side of them. A gap is normal, so
 * the map must say "no imagery for this day" rather than quietly falling back
 * to a day that does have some.
 */

export interface ImageryLayer {
  id: string
  /** What the toggle says. */
  label: string
  /** One line under the toggle, because "nightlights" does not explain itself. */
  hint: string
  /** GIBS layer identifier and its tile format. */
  product: string
  format: "png" | "jpg"
  /** Deepest zoom the product is published at. */
  maxZoom: number
  /** Fixed, not a slider. One more control is one more thing to get wrong. */
  opacity: number
}

export const IMAGERY_LAYERS: readonly ImageryLayer[] = [
  {
    id: "nightlights",
    label: "Nightlights",
    hint: "where the lights are, and where they went out",
    product: "VIIRS_SNPP_DayNightBand_At_Sensor_Radiance",
    format: "png",
    maxZoom: 8,
    opacity: 0.9,
  },
  {
    id: "truecolour",
    label: "True colour",
    hint: "cloud, smoke, dust, flooding",
    product: "MODIS_Terra_CorrectedReflectance_TrueColor",
    format: "jpg",
    maxZoom: 9,
    opacity: 0.7,
  },
] as const

const BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"

/** The UTC day a timestamp falls in, which is how the tiles are addressed. */
export function imageryDate(atMs: number): string {
  return new Date(atMs).toISOString().slice(0, 10)
}

/** Tile template for one layer on one day, or null for an unknown layer. */
export function imageryTiles(layerId: string, date: string): string[] | null {
  const layer = IMAGERY_LAYERS.find((l) => l.id === layerId)
  if (!layer) return null
  const level = `GoogleMapsCompatible_Level${layer.maxZoom}`
  return [`${BASE}/${layer.product}/default/${date}/${level}/{z}/{y}/{x}.${layer.format}`]
}

export function imageryLayer(layerId: string): ImageryLayer | null {
  return IMAGERY_LAYERS.find((l) => l.id === layerId) ?? null
}
