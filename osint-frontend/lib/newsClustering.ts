// Pure news clustering + ranking, extracted from DashboardSection so it can be
// unit-tested in isolation. Collapses the per-article feed into one Story per
// real-world event: outlets covering the same story merge, ranked by how widely
// they were picked up. See docs/superpowers/specs/2026-06-27-news-ranking-dedup-design.md
import type { EventRow } from "./types"

export const TITLE_THRESHOLD = 0.4
export const ENTITY_THRESHOLD = 0.5

/** Editorial source weights for impact ranking. Higher = more credibility /
 *  global reach. Out-of-table sources get 0.5. (Moved from DashboardSection.) */
const NEWS_SOURCE_WEIGHTS: Record<string, number> = {
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

/** 24 h linear-decay recency in [0, 1]; 0 once a row is more than a day old. */
export function recencyFor(ev: EventRow): number {
  const t = new Date(ev.occurred_at).getTime()
  if (!Number.isFinite(t)) return 0
  const ageH = Math.max(0, (Date.now() - t) / 3_600_000)
  return Math.max(0, 1 - ageH / 24)
}

/** Lowercase token + bigram set of a title — Jaccard similarity for clustering. */
export function titleBigrams(title: string): Set<string> {
  const cleaned = title.toLowerCase().replace(/[^a-z0-9\s]/g, " ")
  const tokens = cleaned.split(/\s+/).filter((t) => t.length > 2)
  const out = new Set<string>()
  for (let i = 0; i < tokens.length - 1; i++) out.add(`${tokens[i]}_${tokens[i + 1]}`)
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

/** Tidy outlet label for a row — feed_name when present, else the source slug. */
export function newsSourceLabel(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const feed = typeof p?.feed_name === "string" ? p.feed_name : null
  if (feed) return feed
  return ev.source.replace(/^rss-/, "").replace(/-/g, " ")
}

const ENTITY_LABELS = new Set(["ORG", "GPE", "PERSON", "EVENT", "FAC", "LOC"])

/** Lowercased named-entity texts (orgs / places / people / events) for a row,
 *  used to detect that two reworded headlines describe the same story. */
export function entitySet(ev: EventRow): Set<string> {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  const raw = Array.isArray(p.entities) ? (p.entities as unknown[]) : []
  const out = new Set<string>()
  for (const e of raw) {
    if (typeof e !== "object" || e === null) continue
    const text = (e as { text?: unknown }).text
    const label = (e as { label?: unknown }).label
    if (typeof text === "string" && typeof label === "string" && ENTITY_LABELS.has(label)) {
      const t = text.trim().toLowerCase()
      if (t) out.add(t)
    }
  }
  return out
}

export interface Story {
  rep: EventRow
  members: EventRow[]
  outlets: string[]
  outletCount: number
  topEntity: string | null
}

function storyTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  return (
    (typeof p.title === "string" && p.title) ||
    (typeof p.headline === "string" && p.headline) ||
    ev.source
  )
}

function hasImage(ev: EventRow): boolean {
  const u = (ev.payload as Record<string, unknown>)?.image_url
  return typeof u === "string" && u.startsWith("http")
}

function summaryLen(ev: EventRow): number {
  const s = (ev.payload as Record<string, unknown>)?.summary
  return typeof s === "string" ? s.length : 0
}

/** Best member to show as the story card: prefer one with an image, then the
 *  most authoritative outlet, then the longest summary. */
export function pickRepresentative(members: EventRow[]): EventRow {
  return [...members].sort((a, b) => {
    const ai = hasImage(a) ? 1 : 0
    const bi = hasImage(b) ? 1 : 0
    if (ai !== bi) return bi - ai
    const aw = sourceWeightFor(a)
    const bw = sourceWeightFor(b)
    if (aw !== bw) return bw - aw
    return summaryLen(b) - summaryLen(a)
  })[0]
}

/** Story importance. Cross-outlet pickup dominates: a story carried by many
 *  outlets matters more than a one-off. */
export function storyImpact(story: Story, _now: number): number {
  let sentiment = 0
  let weight = 0
  let recency = 0
  for (const m of story.members) {
    const p = (m.payload ?? {}) as Record<string, unknown>
    sentiment = Math.max(sentiment, typeof p.sentiment === "number" ? Math.abs(p.sentiment) : 0)
    weight = Math.max(weight, sourceWeightFor(m))
    recency = Math.max(recency, recencyFor(m))
  }
  const pickup = Math.min(story.outletCount / 5, 1)
  return 0.35 * pickup + 0.25 * sentiment + 0.2 * weight + 0.2 * recency
}

function computeTopEntity(members: EventRow[]): string | null {
  const counts = new Map<string, number>()
  for (const m of members) for (const t of entitySet(m)) counts.set(t, (counts.get(t) ?? 0) + 1)
  let best: string | null = null
  let bestN = 1
  for (const [t, c] of counts) {
    if (c > bestN || (c === bestN && best === null)) {
      best = t
      bestN = c
    }
  }
  return best ? best.replace(/\b\w/g, (ch) => ch.toUpperCase()) : null
}

/** Group articles into one Story each. Two articles merge when EITHER their
 *  title-bigram Jaccard >= TITLE_THRESHOLD OR their shared-entity Jaccard >=
 *  ENTITY_THRESHOLD (catches reworded headlines about the same event). Single-
 *  link union-find — O(n^2), n <= ~600, fine for the in-buffer news set. */
export function clusterNews(news: EventRow[]): Story[] {
  const n = news.length
  const bigrams = news.map((e) => titleBigrams(storyTitle(e)))
  const ents = news.map((e) => entitySet(e))
  const parent = news.map((_, i) => i)
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]]
      i = parent[i]
    }
    return i
  }
  const union = (a: number, b: number): void => {
    const ra = find(a)
    const rb = find(b)
    if (ra !== rb) parent[ra] = rb
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (
        jaccard(bigrams[i], bigrams[j]) >= TITLE_THRESHOLD ||
        jaccard(ents[i], ents[j]) >= ENTITY_THRESHOLD
      ) {
        union(i, j)
      }
    }
  }
  const groups = new Map<number, EventRow[]>()
  for (let i = 0; i < n; i++) {
    const r = find(i)
    const g = groups.get(r) ?? []
    g.push(news[i])
    groups.set(r, g)
  }
  const out: Story[] = []
  for (const members of groups.values()) {
    const rep = pickRepresentative(members)
    const repLabel = newsSourceLabel(rep)
    const outlets = Array.from(new Set(members.map((m) => newsSourceLabel(m)))).sort((a, b) =>
      a === repLabel ? -1 : b === repLabel ? 1 : 0,
    )
    out.push({
      rep,
      members,
      outlets,
      outletCount: outlets.length,
      topEntity: computeTopEntity(members),
    })
  }
  return out
}
