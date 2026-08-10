// Ranking for the reading page (/news).
//
// The console orders the Situation feed by latest activity: newest first, so a
// reader watching it sees movement. A reading page is a different question —
// "what should I read now?" — and recency alone answers it badly. A single
// outlet republishing every twenty minutes outranks eight independent
// newsrooms that filed an hour ago.
//
// So the order here is a stated mix of four things, each of which the reader
// can see on the row: how many independent owners tell it, how many outlets
// carry it, how fresh the last filing is, and whether it is still escalating.
// Corroboration rides along as a tie-breaker and never gates — a widely-told
// story with few independent owners is exactly what must stay visible (#449).
//
// Pure functions, no fetching, no React, so the weights are testable and the
// ordering is explainable rather than felt.

import type { StoryRow } from "./analytics"

/** Weights. They sum to 1 for readability; only their ratios matter. */
export const WEIGHTS = {
  /** Independent tellers — the strongest signal that something happened. */
  owners: 0.4,
  /** Outlets carrying it — reach, discounted because syndication inflates it. */
  outlets: 0.2,
  /** How recently the story last moved. */
  freshness: 0.3,
  /** Still gathering coverage rather than settling. */
  escalating: 0.1,
} as const

/** Hours after which a story's freshness contribution halves. */
export const FRESHNESS_HALF_LIFE_HOURS = 12

/** Counts saturate: the 8th independent owner adds less than the 2nd. */
function saturate(count: number, midpoint: number): number {
  if (count <= 0) return 0
  return count / (count + midpoint)
}

/** Exponential decay on hours since the story last moved. */
export function freshness(lastSeen: string, now: number): number {
  const ageMs = now - Date.parse(lastSeen)
  if (!Number.isFinite(ageMs)) return 0
  const ageHours = Math.max(0, ageMs) / 3_600_000
  return Math.pow(0.5, ageHours / FRESHNESS_HALF_LIFE_HOURS)
}

export interface RankedStory<T extends StoryRow = StoryRow> {
  story: T
  score: number
  /** Why it sits where it sits, in the order the row shows them. */
  reasons: string[]
}

/** Score one story. Deterministic given `now`. */
export function scoreStory(story: StoryRow, now: number): number {
  const owners = saturate(story.owner_count, 3)
  const outlets = saturate(story.outlet_count, 6)
  const fresh = freshness(story.last_seen, now)
  const escalating = story.escalating === "escalating" ? 1 : 0
  return (
    WEIGHTS.owners * owners +
    WEIGHTS.outlets * outlets +
    WEIGHTS.freshness * fresh +
    WEIGHTS.escalating * escalating
  )
}

/** The short, honest account of why a story ranks where it does. */
export function rankReasons(story: StoryRow): string[] {
  const out: string[] = []
  if (story.owner_count > 1) out.push(`${story.owner_count} independent owners`)
  else out.push("single owner")
  out.push(`${story.outlet_count} ${story.outlet_count === 1 ? "outlet" : "outlets"}`)
  if (story.escalating === "escalating") out.push("still escalating")
  if (story.corroboration !== null) out.push(`corroboration ${story.corroboration.toFixed(2)}`)
  return out
}

/**
 * Rank stories best-first.
 *
 * Ties break on corroboration, then on id, so the same input always produces
 * the same page — a list that reshuffles between refreshes cannot be read.
 */
export function rankStories<T extends StoryRow>(stories: T[], now: number): RankedStory<T>[] {
  return stories
    .map((story) => ({ story, score: scoreStory(story, now), reasons: rankReasons(story) }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score
      const corroA = a.story.corroboration ?? -1
      const corroB = b.story.corroboration ?? -1
      if (corroB !== corroA) return corroB - corroA
      return a.story.id.localeCompare(b.story.id)
    })
}

/** "4h ago", "2d ago" — the reading page's only time format. */
export function relativeAge(iso: string, now: number): string {
  const ms = now - Date.parse(iso)
  if (!Number.isFinite(ms)) return "—"
  const minutes = Math.max(0, Math.round(ms / 60_000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
