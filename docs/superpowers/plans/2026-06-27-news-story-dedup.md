# News Story Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the dashboard news feed to one card per real-world story — cross-outlet de-duplication plus pickup-weighted ranking.

**Architecture:** Extract pure news clustering/ranking logic out of the 1700-line `DashboardSection.tsx` into a new tested module `lib/newsClustering.ts`. The component imports it and renders one card per `Story`.

**Tech Stack:** TypeScript, React (Next.js 15), vitest. Frontend only, no new dependencies.

## Global Constraints

- Branch: `feat/news-story-dedup`. Frontend only. No new dependencies.
- Tests run with `pnpm test` from `osint-frontend/`. `@/` alias → `osint-frontend/`.
- Gates before each commit: `npx tsc --noEmit` clean; `npx eslint <files>` 0 errors; `pnpm test` green.
- Existing card styling/layout is unchanged; only the data feeding it (per-story not per-article) and two new chips (sources pill, topic chip).
- Thresholds: `TITLE_THRESHOLD = 0.4`, `ENTITY_THRESHOLD = 0.5`.

---

### Task 1: newsClustering module — shared helpers + entity extraction

**Files:**
- Create: `osint-frontend/lib/newsClustering.ts`
- Test: `osint-frontend/__tests__/newsClustering.test.ts`

**Interfaces:**
- Consumes: `EventRow` from `@/lib/types`.
- Produces:
  - `titleBigrams(title: string): Set<string>`
  - `jaccard(a: Set<string>, b: Set<string>): number`
  - `sourceWeightFor(ev: EventRow): number`
  - `recencyFor(ev: EventRow): number`
  - `newsSourceLabel(ev: EventRow): string`
  - `entitySet(ev: EventRow): Set<string>` — lowercased ORG/GPE/PERSON/EVENT/FAC/LOC entity texts from `payload.entities`.

- [ ] **Step 1: Write the failing test**

```ts
// osint-frontend/__tests__/newsClustering.test.ts
import { describe, expect, it } from "vitest"
import { entitySet, jaccard, sourceWeightFor, titleBigrams, newsSourceLabel } from "@/lib/newsClustering"
import type { EventRow } from "@/lib/types"

function row(p: Partial<EventRow>): EventRow {
  return { id: "1", source: "rss-bbc-world", occurred_at: new Date().toISOString(), category: "news", severity: 0.3, payload: {}, ...p } as EventRow
}

describe("entitySet", () => {
  it("keeps org/place/person entity texts, lowercased", () => {
    const s = entitySet(row({ payload: { entities: [
      { text: "Japan", label: "GPE" }, { text: "NATO", label: "ORG" },
      { text: "Tuesday", label: "DATE" },
    ] } }))
    expect(s.has("japan")).toBe(true)
    expect(s.has("nato")).toBe(true)
    expect(s.has("tuesday")).toBe(false) // DATE dropped
  })
  it("empty when no entities", () => expect(entitySet(row({ payload: {} })).size).toBe(0))
})

describe("shared helpers", () => {
  it("titleBigrams + jaccard work", () => {
    const a = titleBigrams("strong earthquake japan")
    const b = titleBigrams("strong earthquake japan today")
    expect(jaccard(a, b)).toBeGreaterThan(0.4)
  })
  it("sourceWeightFor known outlet > unknown", () => {
    expect(sourceWeightFor(row({ source: "rss-bbc-world" }))).toBeGreaterThan(
      sourceWeightFor(row({ source: "rss-unknown-blog" })),
    )
  })
  it("newsSourceLabel strips rss- and dashes", () => {
    expect(newsSourceLabel(row({ source: "rss-bbc-world" }))).toBe("bbc world")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: FAIL — cannot find module `@/lib/newsClustering`.

- [ ] **Step 3: Create the module — move the pure helpers + add entitySet**

Move these verbatim from `components/DashboardSection.tsx` into the new file (and delete them from DashboardSection in Task 4): `SOURCE_WEIGHTS` const, `sourceWeightFor`, `recencyFor`, `titleBigrams`, `jaccard`, `newsSourceLabel`. Then add `entitySet`.

```ts
// osint-frontend/lib/newsClustering.ts
import type { EventRow } from "./types"

// --- moved verbatim from DashboardSection (single source of truth) ---
// (copy SOURCE_WEIGHTS, sourceWeightFor, recencyFor, titleBigrams, jaccard,
//  newsSourceLabel exactly as they are today)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: PASS.

- [ ] **Step 5: tsc + commit**

```bash
cd osint-frontend && npx tsc --noEmit
git add osint-frontend/lib/newsClustering.ts osint-frontend/__tests__/newsClustering.test.ts
git commit -m "feat(news): newsClustering module — shared helpers + entity sets"
```

---

### Task 2: clusterNews — group articles into stories

**Files:**
- Modify: `osint-frontend/lib/newsClustering.ts`
- Test: `osint-frontend/__tests__/newsClustering.test.ts`

**Interfaces:**
- Consumes: `entitySet`, `titleBigrams`, `jaccard` (Task 1); `bestTitle` (import from `@/lib/types`? no — define a local `storyTitle(ev)` reading `payload.title || payload.headline || source`).
- Produces:
  - `interface Story { rep: EventRow; members: EventRow[]; outlets: string[]; outletCount: number; topEntity: string | null }`
  - `clusterNews(news: EventRow[]): Story[]` — note `topEntity`/`rep` are finalised in Task 3; for this task set `rep = members[0]`, `topEntity = null`.
  - `TITLE_THRESHOLD = 0.4`, `ENTITY_THRESHOLD = 0.5`.

- [ ] **Step 1: Write the failing test**

```ts
import { clusterNews } from "@/lib/newsClustering"

const T = new Date().toISOString()
const mk = (id: string, source: string, title: string, entities: {text:string;label:string}[] = []) =>
  ({ id, source, occurred_at: T, category: "news", severity: 0.3, payload: { title, entities } }) as unknown as EventRow

describe("clusterNews", () => {
  it("merges the same headline across two outlets into one story", () => {
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Strong earthquake strikes Japan"),
      mk("2", "rss-reuters-world", "Strong earthquake strikes Japan"),
    ])
    expect(stories).toHaveLength(1)
    expect(stories[0].outletCount).toBe(2)
  })
  it("merges reworded headlines that share entities", () => {
    const ents = [{ text: "Japan", label: "GPE" }, { text: "Honshu", label: "GPE" }]
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Quake hits Japan", ents),
      mk("2", "rss-cnn-world", "Powerful tremor rattles Honshu coast", ents),
    ])
    expect(stories).toHaveLength(1)
  })
  it("keeps unrelated headlines as separate stories", () => {
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Election results announced in Brazil"),
      mk("2", "rss-cnn-world", "Tech stocks rally on Wall Street"),
    ])
    expect(stories).toHaveLength(2)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: FAIL — `clusterNews` not exported.

- [ ] **Step 3: Implement clusterNews**

```ts
export const TITLE_THRESHOLD = 0.4
export const ENTITY_THRESHOLD = 0.5

export interface Story {
  rep: EventRow
  members: EventRow[]
  outlets: string[]
  outletCount: number
  topEntity: string | null
}

function storyTitle(ev: EventRow): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>
  return (typeof p.title === "string" && p.title) || (typeof p.headline === "string" && p.headline) || ev.source
}

export function clusterNews(news: EventRow[]): Story[] {
  const n = news.length
  const bigrams = news.map((e) => titleBigrams(storyTitle(e)))
  const ents = news.map((e) => entitySet(e))
  const parent = news.map((_, i) => i)
  const find = (i: number): number => {
    while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i] }
    return i
  }
  const union = (a: number, b: number) => { const ra = find(a), rb = find(b); if (ra !== rb) parent[ra] = rb }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (jaccard(bigrams[i], bigrams[j]) >= TITLE_THRESHOLD || jaccard(ents[i], ents[j]) >= ENTITY_THRESHOLD) {
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
    const outlets = Array.from(new Set(members.map((m) => newsSourceLabel(m))))
    out.push({ rep: members[0], members, outlets, outletCount: outlets.length, topEntity: null })
  }
  return out
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: PASS.

- [ ] **Step 5: tsc + commit**

```bash
cd osint-frontend && npx tsc --noEmit
git add osint-frontend/lib/newsClustering.ts osint-frontend/__tests__/newsClustering.test.ts
git commit -m "feat(news): clusterNews — title + entity dedup into stories"
```

---

### Task 3: pickRepresentative, storyImpact, topEntity

**Files:**
- Modify: `osint-frontend/lib/newsClustering.ts`
- Test: `osint-frontend/__tests__/newsClustering.test.ts`

**Interfaces:**
- Consumes: `Story`, `sourceWeightFor`, `recencyFor`, `entitySet` (earlier tasks).
- Produces:
  - `pickRepresentative(members: EventRow[]): EventRow`
  - `storyImpact(story: Story, now: number): number`
  - `clusterNews` updated so each `Story.rep` = `pickRepresentative(members)` and `Story.topEntity` = most-frequent shared entity (title-cased) or null.

- [ ] **Step 1: Write the failing test**

```ts
import { pickRepresentative, storyImpact, clusterNews } from "@/lib/newsClustering"

describe("pickRepresentative", () => {
  it("prefers a member with an image, then source weight", () => {
    const withImg = mk("1", "rss-unknown-blog", "X")
    ;(withImg.payload as Record<string, unknown>).image_url = "http://x/a.jpg"
    const noImg = mk("2", "rss-bbc-world", "X")
    expect(pickRepresentative([noImg, withImg]).id).toBe("1")
  })
})

describe("storyImpact", () => {
  it("ranks a multi-outlet story above a single-outlet one", () => {
    const now = Date.now()
    const big = clusterNews([
      mk("1","rss-bbc-world","Same big story"), mk("2","rss-reuters-world","Same big story"),
      mk("3","rss-cnn-world","Same big story"),
    ])[0]
    const small = clusterNews([mk("4","rss-bbc-world","Lonely story")])[0]
    expect(storyImpact(big, now)).toBeGreaterThan(storyImpact(small, now))
  })
})

describe("topEntity", () => {
  it("is the most frequent shared entity", () => {
    const ents = [{ text: "Ukraine", label: "GPE" }]
    const s = clusterNews([
      mk("1","rss-bbc-world","War update Ukraine", ents),
      mk("2","rss-cnn-world","Ukraine front line shifts", ents),
    ])[0]
    expect(s.topEntity).toBe("Ukraine")
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: FAIL — `pickRepresentative` / `storyImpact` not exported.

- [ ] **Step 3: Implement + wire into clusterNews**

```ts
export function pickRepresentative(members: EventRow[]): EventRow {
  return [...members].sort((a, b) => {
    const ai = hasImage(a) ? 1 : 0, bi = hasImage(b) ? 1 : 0
    if (ai !== bi) return bi - ai
    const aw = sourceWeightFor(a), bw = sourceWeightFor(b)
    if (aw !== bw) return bw - aw
    return summaryLen(b) - summaryLen(a)
  })[0]
}

function hasImage(ev: EventRow): boolean {
  const u = (ev.payload as Record<string, unknown>)?.image_url
  return typeof u === "string" && u.startsWith("http")
}
function summaryLen(ev: EventRow): number {
  const s = (ev.payload as Record<string, unknown>)?.summary
  return typeof s === "string" ? s.length : 0
}

export function storyImpact(story: Story, now: number): number {
  let sentiment = 0, weight = 0, recency = 0
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
  let best: string | null = null, bestN = 1
  for (const [t, c] of counts) if (c > bestN || (c === bestN && best === null)) { best = t; bestN = c }
  return best ? best.replace(/\b\w/g, (ch) => ch.toUpperCase()) : null
}
```

In `clusterNews`, replace the push with:
```ts
out.push({
  rep: pickRepresentative(members),
  members,
  outlets,
  outletCount: outlets.length,
  topEntity: computeTopEntity(members),
})
```
(Reorder `outlets` so the rep's label is first: `const repLabel = newsSourceLabel(rep); outlets.sort((a) => (a === repLabel ? -1 : 0))`.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd osint-frontend && pnpm test newsClustering`
Expected: PASS (all clustering tests).

- [ ] **Step 5: tsc + commit**

```bash
cd osint-frontend && npx tsc --noEmit
git add osint-frontend/lib/newsClustering.ts osint-frontend/__tests__/newsClustering.test.ts
git commit -m "feat(news): representative pick + pickup-weighted story impact + topEntity"
```

---

### Task 4: render one card per story in DashboardSection

**Files:**
- Modify: `osint-frontend/components/DashboardSection.tsx`

**Interfaces:**
- Consumes: `clusterNews`, `storyImpact`, `Story`, and the moved helpers from `@/lib/newsClustering`.

- [ ] **Step 1: Remove the moved helpers + import from the module**

Delete the now-duplicated `SOURCE_WEIGHTS`, `sourceWeightFor`, `recencyFor`, `titleBigrams`, `jaccard`, `newsSourceLabel` from DashboardSection. Add:
```ts
import { clusterNews, storyImpact, newsSourceLabel, sourceWeightFor, recencyFor, type Story } from "@/lib/newsClustering"
```
(Keep `bestTitle`, `bestSummary`, `impactScoreFor` in DashboardSection — `impactScoreFor` may now be unused; delete it if so.)

- [ ] **Step 2: Replace `newsClusters` + `filteredNews` with stories**

```ts
const stories = useMemo(() => clusterNews(allNews), [allNews])

const filteredStories = useMemo(() => {
  const f = NEWS_FILTERS.find((x) => x.key === newsFilter) ?? NEWS_FILTERS[0]
  const matched = stories.filter((s) => s.members.some(f.match))
  const now = Date.now()
  if (newsSort === "impact") {
    return [...matched].sort((a, b) => storyImpact(b, now) - storyImpact(a, now)).slice(0, 30)
  }
  return [...matched]
    .sort((a, b) => +new Date(b.rep.occurred_at) - +new Date(a.rep.occurred_at))
    .slice(0, 30)
}, [stories, newsFilter, newsSort])
```
Update the filter-button counts to `stories.filter((s) => s.members.some(f.match)).length` (and `stories.length` for "all").

- [ ] **Step 3: Render one card per story**

Change `filteredNews.map((ev) => …)` to `filteredStories.map((story) => { const ev = story.rep; … })` (the card body already reads `ev`). Inside the card header area, add the sources pill + topic chip:
```tsx
<div className="mt-1 flex flex-wrap items-center gap-1">
  {story.topEntity && (
    <span className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-neutral-300">
      {story.topEntity}
    </span>
  )}
  {story.outletCount > 1 && (
    <span className="rounded bg-cyan-950/40 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-cyan-300">
      {story.outletCount} sources · {story.outlets.slice(0, 2).join(" · ")}
      {story.outletCount > 2 ? ` +${story.outletCount - 2}` : ""}
    </span>
  )}
</div>
```
Replace the old per-article `clusterSize` badge usage with `story.outletCount`. Use `key={story.rep.id}`.

- [ ] **Step 4: Gates**

Run: `cd osint-frontend && npx tsc --noEmit && npx eslint components/DashboardSection.tsx lib/newsClustering.ts && pnpm test`
Expected: tsc clean, eslint 0 errors, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/components/DashboardSection.tsx
git commit -m "feat(news): render one card per story with sources pill + topic chip"
```

---

### Task 5: verification + PR

- [ ] **Step 1: Full gate**

Run: `cd osint-frontend && npx tsc --noEmit && npx eslint . && pnpm test`
Expected: tsc clean; eslint 0 errors; all vitest pass (newsClustering + existing).

- [ ] **Step 2: Visual check**

Hard-refresh the dashboard, scroll to the News feed. Confirm: duplicate stories collapse to one card with a `N sources · BBC · Reuters …` pill; topic chip shows; impact sort puts widely-covered stories on top; region filters + impact/time sort still work.

- [ ] **Step 3: Push + PR**

```bash
git push -u origin feat/news-story-dedup
gh pr create --base main --title "feat(news): one card per story — cross-outlet dedup + ranking" --body "Closes #212. ..."
```
Do NOT merge — Basil merges.

## Self-Review

**Spec coverage:** one-card-per-story → Tasks 2+4 ✓; title+entity dedup → Task 2 ✓; representative pick → Task 3 ✓; pickup-weighted ranking → Task 3 ✓; sources pill + topic chip → Task 4 ✓; pure tested module → Tasks 1-3 ✓; fallbacks (no entities/image/single outlet) → covered by entitySet empty, hasImage false, outletCount===1 guards ✓.

**Type consistency:** `Story`, `clusterNews`, `storyImpact`, `pickRepresentative`, `entitySet`, `newsSourceLabel`, `sourceWeightFor`, `recencyFor` names consistent across tasks. `storyImpact(story, now)` signature used consistently in Task 3 + Task 4.
