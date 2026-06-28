import type { VisibleEvent } from "./queries"

export interface WorldNewsAggregate {
  country: string
  lat: number
  lon: number
  events: VisibleEvent[]
}

export function isWorldScopeNews(ev: VisibleEvent): boolean {
  const source = (ev.source ?? "").toLowerCase()
  if (!source.startsWith("rss-")) return false
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const scope = typeof p.news_scope === "string" ? p.news_scope : null
  return scope === "world" || scope === "unknown"
}

export function worldNewsAggregates(
  events: VisibleEvent[],
  centroids: Map<string, [number, number]>,
): WorldNewsAggregate[] {
  const byCountry = new Map<string, VisibleEvent[]>()
  for (const ev of events) {
    if (!isWorldScopeNews(ev) || !ev.country) continue
    const arr = byCountry.get(ev.country) ?? []
    arr.push(ev)
    byCountry.set(ev.country, arr)
  }

  const out: WorldNewsAggregate[] = []
  for (const [country, rows] of byCountry) {
    const centroid = centroids.get(country)
    if (!centroid) continue
    out.push({
      country,
      lon: centroid[0],
      lat: centroid[1],
      events: rows.sort((a, b) => +new Date(b.occurred_at) - +new Date(a.occurred_at)),
    })
  }
  return out.sort((a, b) => b.events.length - a.events.length)
}
