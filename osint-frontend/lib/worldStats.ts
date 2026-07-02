/** Pure aggregation for the ACLED-style world status panel (right pane,
 *  default "world" mode). Derives real metrics from the live event buffer —
 *  no faked fatalities / exposure. Kept side-effect-free so it can be unit
 *  tested in isolation and reused from any surface (#252).
 */

import type { EventRow } from "./types"

export interface CountryFrequency {
  /** ISO2 country code. */
  country: string
  count: number
}

export interface WorldStats {
  /** Total events in the buffer / window. */
  total: number
  /** Distinct countries with at least one event. */
  activeCountries: number
  /** Distinct sources currently emitting. */
  activeSources: number
  /** Countries ranked by event count, desc, capped at `topN`. */
  topCountries: CountryFrequency[]
  /** Event counts bucketed oldest→newest across the observed time span,
   *  for the sparkline. Length === `sparkBuckets` (0-filled when empty). */
  spark: number[]
}

export const WORLD_STATS_TOP_N = 12
export const WORLD_STATS_SPARK_BUCKETS = 24

export function worldStats(
  events: EventRow[],
  topN = WORLD_STATS_TOP_N,
  sparkBuckets = WORLD_STATS_SPARK_BUCKETS,
): WorldStats {
  const byCountry = new Map<string, number>()
  const sources = new Set<string>()
  let minT = Infinity
  let maxT = -Infinity

  for (const ev of events) {
    if (ev.country) byCountry.set(ev.country, (byCountry.get(ev.country) ?? 0) + 1)
    if (ev.source) sources.add(ev.source)
    const t = new Date(ev.occurred_at).getTime()
    if (Number.isFinite(t)) {
      if (t < minT) minT = t
      if (t > maxT) maxT = t
    }
  }

  const topCountries = [...byCountry.entries()]
    .map(([country, count]) => ({ country, count }))
    .sort((a, b) => b.count - a.count || a.country.localeCompare(b.country))
    .slice(0, topN)

  const spark = new Array<number>(sparkBuckets).fill(0)
  if (Number.isFinite(minT) && maxT > minT) {
    const span = maxT - minT
    for (const ev of events) {
      const t = new Date(ev.occurred_at).getTime()
      if (!Number.isFinite(t)) continue
      let idx = Math.floor(((t - minT) / span) * sparkBuckets)
      if (idx >= sparkBuckets) idx = sparkBuckets - 1
      if (idx < 0) idx = 0
      spark[idx] += 1
    }
  }

  return {
    total: events.length,
    activeCountries: byCountry.size,
    activeSources: sources.size,
    topCountries,
    spark,
  }
}
