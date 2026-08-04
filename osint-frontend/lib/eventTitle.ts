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

export function eventHeadline(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>

  const given =
    (typeof p.title === "string" && p.title.trim()) ||
    (typeof p.headline === "string" && p.headline.trim()) ||
    null
  if (given) return given

  //: No headline yet. Say where it came from and where it happened rather
  //: than dressing a CAMEO bucket up as a description of the article.
  const host = sourceHost(p.source_url)
  const place = placeName(p)
  if (host && place) return `${host} · ${place}`
  if (host) return host
  if (place) return `${ev.source.replace(/^rss-/, "")} · ${place}`
  return ev.source.replace(/^rss-/, "")
}
