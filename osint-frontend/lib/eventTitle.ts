import type { EventRow } from "@/lib/types"

/**
 * What a row says it is (#788).
 *
 * GDELT's export carries no headline, only a CAMEO root code, and the label
 * for that code was being printed where a headline belongs — so a selection
 * over one city read `Coerce · Edinburgh` four times down the panel.
 *
 * The label is not a description of the article. Sampled against the source
 * URL's own slug, `Coerce` covered a credit union's tornado donation, a
 * missing-boy rescue and a guilty-plea reversal. A row must say what its
 * article says, and until the title beat has fetched that, it says where it
 * came from and where it happened — both true, neither pretending.
 */

/** The outlet's domain, as a person would say it: `rte.ie`, `bbc.co.uk`. */
export function sourceHost(url: unknown): string | null {
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return null
  try {
    return new URL(url).hostname.replace(/^www\./, "") || null
  } catch {
    return null
  }
}

/** The place free-text GDELT attached, trimmed to its first part.
 *  `"Neenah, Wisconsin, United States"` → `"Neenah"`. */
function placeName(payload: Record<string, unknown>): string | null {
  const raw = payload.geo_name ?? payload.country_fips
  if (typeof raw !== "string") return null
  return raw.split(",")[0]?.trim() || null
}

/** What an instrument reading says, for the sources that publish no prose.
 *
 *  Search can now find these (#938) — a fire detection is tagged `fire` and a
 *  quake `earthquake`, so "wildfires" returns them. Without this they all fell
 *  through to the source name, and a search for wildfires answered with forty
 *  rows each reading `nasa-firms`. A list of forty identical strings is not a
 *  list of results.
 *
 *  Each of these is the row's own field, never a guess: USGS names the place
 *  it measured, GDACS names its event, abuse.ch classifies the threat. Where a
 *  source carries nothing to say, this returns null and the caller falls back
 *  as before. */
function readingHeadline(ev: EventRow, p: Record<string, unknown>): string | null {
  const src = ev.source.toLowerCase()
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null)

  //: "10 km SW of Ridgecrest, California" — the whole claim, already written.
  if (src.startsWith("usgs")) {
    const place = str(p.place)
    const mag = typeof p.magnitude === "number" ? `M${p.magnitude.toFixed(1)}` : null
    if (place && mag) return `${mag} earthquake · ${place}`
    if (place) return `Earthquake · ${place}`
    if (mag) return `${mag} earthquake`
  }

  if (src.startsWith("gdacs")) {
    const name = str(p.eventname) ?? str(p.country_name)
    if (name) return name
  }

  //: A fire detection is one satellite pixel, so the only thing that
  //: distinguishes one row from the next is where and how hot.
  if (src.startsWith("nasa-firms")) {
    const where = ev.country ? ` · ${ev.country}` : ""
    const frp = Number(p.frp)
    const power = Number.isFinite(frp) ? ` · ${frp.toFixed(0)} MW` : ""
    return `Fire detection${where}${power}`
  }

  if (src.startsWith("abuse-ch")) {
    const threat = str(p.threat)?.replace(/_/g, " ")
    const host = sourceHost(p.url)
    if (threat && host) return `${threat} · ${host}`
    if (threat) return threat
  }

  if (src.startsWith("opensky") || src.startsWith("adsb")) {
    const n = Number(p.aircraft_count)
    if (Number.isFinite(n)) {
      const where = ev.country ? ` · ${ev.country}` : ""
      return `${n} aircraft tracked${where}`
    }
  }

  return null
}

export function eventHeadline(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>

  const given =
    (typeof p.title === "string" && p.title.trim()) ||
    (typeof p.headline === "string" && p.headline.trim()) ||
    null
  if (given) return given

  const reading = readingHeadline(ev, p)
  if (reading) return reading

  //: No headline yet. Say where it came from and where it happened rather
  //: than dressing a CAMEO bucket up as a description of the article.
  const host = sourceHost(p.source_url)
  const place = placeName(p)
  if (host && place) return `${host} · ${place}`
  if (host) return host
  if (place) return `${ev.source.replace(/^rss-/, "")} · ${place}`
  return ev.source.replace(/^rss-/, "")
}
