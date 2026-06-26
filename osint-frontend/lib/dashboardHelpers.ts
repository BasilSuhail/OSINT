/** Pure helpers used by DashboardSection.tsx panels.
 *
 *  Extracted to a standalone module so they can be unit-tested in
 *  isolation (#188) and reused from other dashboard surfaces without
 *  pulling the whole DashboardSection component into the bundle.
 *
 *  Nothing here touches React state or the network — every export is a
 *  pure function over its inputs.
 */

import type { EventRow } from "./types"

export function severityBarColor(s: number): string {
  if (s >= 0.8) return "#ef4444"
  if (s >= 0.6) return "#f97316"
  if (s >= 0.4) return "#eab308"
  return "#22c55e"
}

/** VADER compound ∈ [-1, 1] → bar colour. Negative = rose, positive =
 *  emerald, neutral = neutral. */
export function sentimentBarColor(compound: number): string {
  if (compound <= -0.5) return "#e11d48"
  if (compound <= -0.05) return "#f43f5e"
  if (compound >= 0.5) return "#10b981"
  if (compound >= 0.05) return "#34d399"
  return "#737373"
}

/** Editorial per-feed source weights for the impact ranking. */
export const NEWS_SOURCE_WEIGHTS: Record<string, number> = {
  "rss-bbc-world": 1.0,
  "rss-reuters-world": 1.0,
  "rss-nyt-world": 0.95,
  "rss-bbc-uk": 0.95,
  "rss-guardian-world": 0.9,
  "rss-aljazeera": 0.9,
  "rss-france24-en": 0.85,
  "rss-dw-world": 0.85,
  "rss-nhk-world": 0.85,
  "rss-cbc-world": 0.85,
  "rss-abc-au-world": 0.85,
  "rss-cnn-world": 0.8,
  "rss-dawn": 0.85,
  "rss-tribune-pk": 0.75,
  "rss-times-of-india": 0.8,
  "rss-the-hindu": 0.8,
  "rss-straits-times-world": 0.8,
  "rss-rnz-world": 0.8,
  "rss-arab-news": 0.7,
  "rss-jpost-world": 0.75,
  "rss-haaretz-en": 0.8,
  "rss-kyiv-independent": 0.8,
  "rss-geo-english": 0.7,
  "rss-rt-news": 0.55,
  "rss-tass-en": 0.55,
  "uk-police": 0.6,
}

export function sourceWeightFor(ev: EventRow): number {
  return NEWS_SOURCE_WEIGHTS[ev.source] ?? 0.5
}

/** 24 h linear-decay recency in [0, 1]. */
export function recencyFor(ev: EventRow): number {
  const t = new Date(ev.occurred_at).getTime()
  if (!Number.isFinite(t)) return 0
  const ageH = Math.max(0, (Date.now() - t) / 3_600_000)
  return Math.max(0, 1 - ageH / 24)
}

/** Lowercase character-bigram-style shingle set of a title — used for
 *  Jaccard similarity in the article-clustering memo (#172). */
export function titleBigrams(title: string): Set<string> {
  const cleaned = title.toLowerCase().replace(/[^a-z0-9\s]/g, " ")
  const tokens = cleaned.split(/\s+/).filter((t) => t.length > 2)
  const out = new Set<string>()
  for (let i = 0; i < tokens.length - 1; i++) {
    out.add(`${tokens[i]}_${tokens[i + 1]}`)
  }
  for (const t of tokens) out.add(t)
  return out
}

export function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let inter = 0
  for (const x of a) if (b.has(x)) inter += 1
  const uni = a.size + b.size - inter
  return uni === 0 ? 0 : inter / uni
}

/** Impact score per NIP §3. clusterSize defaults to 1 so call sites that
 *  haven't computed clusters (e.g. Hindsight panel) still produce a
 *  meaningful number. */
export function impactScoreFor(ev: EventRow, clusterSize: number = 1): number {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const rawSentiment =
    typeof p?.sentiment === "number"
      ? Math.abs(p.sentiment as number)
      : typeof ev.severity === "number"
        ? Math.abs(ev.severity - 0.35) * 2
        : 0
  const clusterTerm = Math.min(clusterSize / 10, 1)
  return (
    0.3 * rawSentiment +
    0.25 * clusterTerm +
    0.25 * sourceWeightFor(ev) +
    0.2 * recencyFor(ev)
  )
}
