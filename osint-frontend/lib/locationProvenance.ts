import type { EventRow } from "./types"

export type LocationPrecision = "exact-place" | "city" | "region" | "unknown"

/** Evidence owned by one rendered marker, not merely by its story row. */
export interface MarkerLocationContext {
  lat?: number | null
  lon?: number | null
  name?: string | null
  precision?: string | null
  source?: string | null
  wikidataId?: string | null
  description?: string | null
  checkedAt?: string | null
  model?: string | null
}

export interface LocationProvenance {
  precision: LocationPrecision
  precisionDetail: string | null
  name: string | null
  sourceLabel: string
  sourceUrl: string | null
  sourceId: string | null
  checkedAt: string | null
  description: string | null
  model: string | null
  lat: number | null
  lon: number | null
  note: string
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function precision(raw: string | null): {
  value: LocationPrecision
  detail: string | null
  note: string
} {
  const value = (raw ?? "").trim().toLowerCase()
  if (["building", "street", "site", "venue", "exact", "exact-place"].includes(value)) {
    return {
      value: "exact-place",
      detail: value && !["exact", "exact-place"].includes(value) ? value : null,
      note: "Verified place coordinates; not a city or country centroid.",
    }
  }
  if (value === "city") {
    return {
      value: "city",
      detail: null,
      note: "City-level coordinates; no street or building is claimed.",
    }
  }
  if (["region", "admin", "administrative-area"].includes(value)) {
    return {
      value: "region",
      detail: value === "admin" ? "administrative area" : null,
      note: "Region-level coordinates; no city or exact site is claimed.",
    }
  }
  return {
    value: "unknown",
    detail: null,
    note: "Coordinate precision is not recorded.",
  }
}

function sourceLabel(raw: string | null, eventSource: string): string {
  const value = (raw ?? "").trim().toLowerCase()
  if (value === "wikidata") return "Wikidata"
  if (value === "natural-earth") return "Natural Earth gazetteer"
  if (value === "country-centroid") return "Country centroid fallback"
  if (value === "multiple-marker-cluster") return "Multiple marker locations"
  if (value) return value.replaceAll("-", " ")

  const source = eventSource.toLowerCase()
  if (source === "gdelt") return "GDELT source geocode"
  if (source === "acled") return "ACLED source coordinates"
  if (source === "usgs-quake") return "USGS reported epicentre"
  if (source === "gdacs") return "GDACS reported location"
  if (source === "eonet") return "NASA EONET reported location"
  if (source === "emdat") return "EM-DAT reported location"
  if (source === "uk-police") return "UK Police reported location"
  if (source.startsWith("abuse-ch-")) return "abuse.ch geolocation"
  return "Not recorded"
}

function firstGeoName(value: unknown): string | null {
  const name = text(value)
  return name ? text(name.split(",")[0]) : null
}

/** Build the exact wording rendered in marker detail.
 *
 * A marker context wins over row-level fields. One story may own several
 * Wikidata places, while its database row keeps only the first as the legacy
 * primary coordinate. Using the row alone would mislabel every secondary dot.
 */
export function locationProvenanceForEvent(
  event: EventRow,
  marker?: MarkerLocationContext,
): LocationProvenance {
  const payload = (event.payload ?? {}) as Record<string, unknown>
  const hasMarkerContext = marker !== undefined
  const basis = text(payload.geo_basis)?.toLowerCase() ?? null
  const city = text(payload.city)
  const rowPrecision =
    text(payload.geo_precision) ??
    (city && ["city", "term"].includes(basis ?? "") ? "city" : null) ??
    (basis === "region" ? "region" : null)
  const rawPrecision = hasMarkerContext ? text(marker.precision) : rowPrecision
  const classified = precision(rawPrecision)
  const wikidataId = hasMarkerContext
    ? text(marker.wikidataId)
    : text(payload.place_wikidata_id)
  const rawSource =
    text(marker?.source) ??
    text(payload.geo_source) ??
    (wikidataId ? "wikidata" : null) ??
    ((classified.value === "city" || classified.value === "region") &&
    event.source.toLowerCase().startsWith("rss-")
      ? "natural-earth"
      : null)
  const isWikidata = rawSource?.toLowerCase() === "wikidata" || Boolean(wikidataId)
  const rowName =
    text(payload.place_name) ??
    city ??
    firstGeoName(payload.geo_name) ??
    text(payload.region) ??
    text(payload.location) ??
    text(payload.place) ??
    text(payload.geo_city) ??
    text(payload.country_name) ??
    text(payload.geo_country)
  const name = hasMarkerContext ? text(marker.name) : rowName
  const lat = hasMarkerContext ? finite(marker.lat) : finite(event.lat)
  const lon = hasMarkerContext ? finite(marker.lon) : finite(event.lon)

  return {
    precision: classified.value,
    precisionDetail: classified.detail,
    name,
    sourceLabel: sourceLabel(rawSource, event.source),
    sourceUrl:
      isWikidata && wikidataId && /^Q\d+$/.test(wikidataId)
        ? `https://www.wikidata.org/wiki/${wikidataId}`
        : null,
    sourceId: isWikidata ? wikidataId : null,
    checkedAt: isWikidata
      ? hasMarkerContext
        ? text(marker.checkedAt)
        : text(payload.place_checked_at)
      : null,
    description: hasMarkerContext
      ? text(marker.description)
      : text(payload.place_description),
    model: isWikidata
      ? hasMarkerContext
        ? text(marker.model)
        : text(payload.place_model)
      : null,
    lat,
    lon,
    note:
      rawSource?.toLowerCase() === "country-centroid"
        ? "Country-level fallback only; no local event position is known."
        : rawSource?.toLowerCase() === "multiple-marker-cluster"
          ? "This story has several points in this cluster. Zoom in and select one marker for exact evidence."
        : classified.note,
  }
}
