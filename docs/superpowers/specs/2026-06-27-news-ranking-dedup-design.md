# Design — News ranking + de-duplication (one card per story)

Date: 2026-06-27
Status: approved
Scope: frontend only, no new dependencies

## Problem

The dashboard news feed (`components/DashboardSection.tsx`, scroll-down) renders
**one card per article**. When BBC, Reuters and Al Jazeera all cover the same
event, the feed shows three near-identical cards with only a small cluster-size
badge to hint they are related. It reads noisy and repetitive.

Two weaknesses underneath:

1. **De-dup is title-bigram only** (`titleBigrams` + Jaccard ≥ 0.4, single-link
   union-find). Reworded headlines about the same event ("Quake hits Japan" vs
   "Strong earthquake strikes Honshu") share few bigrams and slip through.
2. **Ranking under-weights cross-outlet pickup.** A story carried by 6 outlets is
   far more important than a one-off, yet `impactScoreFor` caps the cluster term
   at 0.25 weight and the feed still lists every member separately.

The NER entities already enriched onto each row (`payload.entities`, spaCy) are
**unused for de-dup** today.

## Goal

Collapse each real-world story into **one card**, ranked by importance, with the
covering outlets surfaced — so the feed reads like a proper wire desk, not an
RSS dump.

## Architecture

`DashboardSection.tsx` is ~1700 lines. Extract the news clustering/ranking logic
into a focused, pure, unit-tested module so the component only renders.

### New: `lib/newsClustering.ts` (pure functions, no React)

```ts
export interface Story {
  rep: EventRow            // representative article (best card to show)
  members: EventRow[]      // all articles in the story (incl. rep)
  outlets: string[]        // distinct outlet labels, rep's first
  outletCount: number      // distinct outlet count (cross-outlet pickup)
  topEntity: string | null // dominant shared entity → topic chip
}

// Group articles into one story each. Two articles merge when EITHER
//   - title-bigram Jaccard >= TITLE_THRESHOLD (existing signal), OR
//   - shared-entity Jaccard >= ENTITY_THRESHOLD (new; catches rewordings)
// Single-link union-find over the news list (O(n^2), n<=~600 — fine).
export function clusterNews(news: EventRow[]): Story[]

// Best member to show: has image_url -> highest sourceWeight -> longest summary.
export function pickRepresentative(members: EventRow[]): EventRow

// Importance of a whole story. Cross-outlet pickup dominates.
//   0.35 * pickup + 0.25 * sentiment + 0.20 * sourceWeight + 0.20 * recency
// pickup = min(outletCount / 5, 1)
export function storyImpact(story: Story, now: number): number
```

- `sourceWeightFor`, `recencyFor`, `titleBigrams`, `bestTitle`, entity extraction
  helpers move (or are imported) so both the module and the component share one
  source of truth. Entity helper: read `payload.entities` (array of `{text,label}`),
  normalise text to lowercase, keep ORG/GPE/PERSON/EVENT/FAC/LOC labels for the
  similarity set; `topEntity` = most frequent entity text across members
  (prefer ORG/GPE), title-cased for display.
- Thresholds: `TITLE_THRESHOLD = 0.4` (unchanged), `ENTITY_THRESHOLD = 0.5`
  (≥ half the smaller entity set shared). Tunable consts at top of file.

### Changed: `DashboardSection.tsx`

- Replace the inline `newsClusters` + per-article `filteredNews` with
  `clusterNews(allNews)` → `stories`, filtered by the active `NEWS_FILTERS`
  (a story matches a filter if ANY member matches), sorted by `storyImpact`,
  top 30.
- Render **one card per story**:
  - rep title / summary / image (existing card layout, unchanged styling)
  - a **sources pill**: `outletCount` + the distinct outlets, e.g.
    `BBC · Reuters · +3` (show first 2–3, "+N" overflow)
  - a **topic chip** = `topEntity` when present
  - link → rep's `source_url`
- The "impact / time" sort + region filters keep working against stories.

## Data flow

events (buffer) → `allNews` filter (rss-/news/uk-police) → `clusterNews` →
`stories` → region filter → `storyImpact` sort → top 30 → cards.

## Error handling / fallbacks

- No entities on a row → entity set empty → falls back to title-bigram merge only.
- No image on the rep → existing first-letter tile fallback.
- Single-outlet story → no "+N", just the one outlet; topic chip hidden if no entity.
- Empty news → existing empty-state message.

## Testing (vitest, `__tests__/newsClustering.test.ts`)

- Two outlets, same headline → 1 story, outletCount 2, outlets has both.
- Reworded headline sharing entities (low bigram overlap) → still merges.
- Unrelated headlines → stay separate stories.
- `pickRepresentative` prefers the member with an image, then source weight.
- `storyImpact` ranks a 6-outlet story above a 1-outlet story with equal sentiment.
- `topEntity` = the most frequent shared org/place.

## Out of scope (later sub-projects)

- Article summaries (no-LLM extractive) — separate spec.
- New / rebalanced RSS feeds — separate spec.
