/** Density cells for the zooms where the map cannot draw rows (#1030).
 *
 *  Below `COMPLETE_VIEWPORT_ZOOM` the map is fed by a page of rows and clusters
 *  them in the browser. It clusters them to count them and holds them to
 *  cluster them, so the page size is what the world view can know: 43,748
 *  events occurred in a measured three-day window against a page of 5,000, and
 *  the world view showed about eight hours of it without saying so.
 *
 *  `/events/grid` counts server-side instead. This turns those counts into the
 *  shape MapLibre already draws a numbered bubble from, so the presentation is
 *  the one readers know and only the arithmetic moves.
 */

export interface GridCell {
  lat: number
  lon: number
  cell_deg: number
  category: string | null
  count: number
  max_severity: number | null
}

export interface GridFeature {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: GridFeatureProperties
}

export interface GridFeatureCollection {
  type: "FeatureCollection"
  features: GridFeature[]
}

export interface GridFeatureProperties {
  point_count: number
  point_count_abbreviated: string
  max_severity: number | null
}

/** MapLibre's own abbreviation, reproduced so a cell reads like a cluster.
 *
 *  Supercluster writes `point_count_abbreviated` itself; these bubbles are not
 *  clusters, so nothing writes it for them and the layer would print nothing. */
export function abbreviateCount(count: number): string {
  if (count >= 10_000) return `${Math.round(count / 1000)}k`
  if (count >= 1_000) return `${(count / 1000).toFixed(1)}k`
  return String(count)
}

/**
 * Fold one row per cell and category into one feature per cell.
 *
 * Hazards are left out. They arrive by a dedicated poll of a few hundred rows,
 * so every one of them is already on the map as its own marker — counting them
 * again in a density cell would draw the same event twice.
 *
 * A cell is keyed by its south-west corner; the feature sits at its centre, so
 * a bubble is over the ground it counts rather than at the corner of it.
 */
export function gridCellsToFeatures(
  cells: GridCell[],
): GridFeatureCollection {
  const byCell = new Map<
    string,
    { lat: number; lon: number; cellDeg: number; count: number; severity: number | null }
  >()

  for (const cell of cells) {
    if (cell.category === "hazard") continue
    if (!Number.isFinite(cell.lat) || !Number.isFinite(cell.lon)) continue
    if (!(cell.count > 0)) continue
    const key = `${cell.lat},${cell.lon}`
    const found = byCell.get(key)
    if (found) {
      found.count += cell.count
      if (cell.max_severity !== null) {
        found.severity = found.severity === null ? cell.max_severity : Math.max(found.severity, cell.max_severity)
      }
      continue
    }
    byCell.set(key, {
      lat: cell.lat,
      lon: cell.lon,
      cellDeg: cell.cell_deg,
      count: cell.count,
      severity: cell.max_severity,
    })
  }

  return {
    type: "FeatureCollection",
    features: [...byCell.values()].map((cell): GridFeature => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [cell.lon + cell.cellDeg / 2, cell.lat + cell.cellDeg / 2],
      },
      properties: {
        point_count: cell.count,
        point_count_abbreviated: abbreviateCount(cell.count),
        max_severity: cell.severity,
      },
    })),
  }
}

/**
 * How coarse a cell should be at this zoom.
 *
 * Halved per zoom level so a cell stays roughly the same size on screen as the
 * map is zoomed, and clamped: the endpoint refuses anything outside its own
 * bounds, and a whole-world request at a fine resolution is a large answer to
 * a question nobody can read at that size.
 */
export function cellDegForZoom(zoom: number): number {
  const raw = 8 / 2 ** Math.max(0, Math.floor(zoom))
  return Math.min(8, Math.max(0.25, raw))
}
