# Story-cluster threshold audit — verdicts (WS-C step 1, issue #334)

*Audited 2026-07-08 against the live stories table (stories-v1.0, joining
threshold 0.35). Sample: 30 clusters via `make stories-audit` (seed 334 —
deterministic, reproducible), stratified: largest by members / loudest by
outlets / random multi-member / random singletons, restricted to clusters
whose member events survive retention (966 of 2,644 at audit time). Sheet:
`data/exports/stories-audit.md`.*

## Verdicts

| story | stratum | members | verdict | note |
|---|---|---|---|---|
| 1561 | random-multi | 2 (1 shown) | coherent | partial evidence — 1 member pruned; fragment of the Khamenei funeral story (see splits) |
| 1639 | random-multi | 3 (2 shown) | coherent | Starmer / kick-off row |
| 1769 | random-singleton | 1 | coherent | match report, correctly separate from the kick-off row (1639) |
| 1750 | loudest | 4 | coherent | Venezuela quake toll |
| 1803 | largest | 7 | coherent | Hamas dissolves Gaza body; one duplicate feed echo |
| 1807 | random-singleton | 1 | coherent | |
| 1801 | random-multi | 4 | coherent | France wildfire; one duplicate feed echo |
| 1964 | largest | 5 | coherent | Sri Lanka prison riot |
| 2053 | random-multi | 3 | **over-merged** | Tour de France stage 3 + stage 4 chained by "tour de france / yellow jersey" tokens — same series, wrong granularity |
| 2067 | random-singleton | 1 | coherent | |
| 2145 | random-multi | 2 | coherent | |
| 1796 | loudest | 4 | coherent | DRC Ebola toll |
| 1962 | loudest | 4 | coherent | Microsoft layoffs |
| 1902 | largest | 12 | coherent-as-saga | Balogun red-card saga: appeal → Trump call → FIFA ruling. Beats of one story, joined correctly |
| 1581 | largest | 7 (4 shown) | **over-merged** | celebrity saga chaining: wedding + honeymoon + unrelated-beat tabloid items |
| 2326 | random-multi | 2 | coherent | |
| 2362 | largest | 5 | coherent | Monaco bombing suspect |
| 2400 | random-multi | 3 | coherent | Harry privacy case |
| 2472 | random-multi | 2 | coherent | same match, two-part explainer |
| 2507 | loudest | 4 | coherent | Argentina–Egypt result |
| 2542 | random-singleton | 1 | coherent | follow-up beat of 2400, acceptably separate |
| 2607 | random-singleton | 1 | coherent | |
| 2618 | random-multi | 2 | coherent | coach-reaction beat, acceptably separate from 2507 |
| 2630 | loudest | 5 | coherent | Hormuz strikes |
| 1804 | largest | 8 | coherent | Khamenei funeral — but see splits: 1710 and 1561 carry the same story |
| 1844 | largest | 5 | coherent | China missile test |
| 2004 | largest | 6 | coherent | Austrian torture verdict; one near-duplicate echo |
| 1754 | largest | 13 | coherent-as-saga | Le Pen verdict → candidacy beats; splits 2368/2389/1961 exist |
| 2155 | largest | 11 | coherent | Macron Syria visit incl. blasts-during-visit beats — one narrative |
| 1777 | random-multi | 2 | coherent | exact duplicate ingestion echo, same outlet (outlet_count correctly 1) |

**Tally: 28 coherent, 2 over-merged, 0 cross-topic contaminations.**
Both over-merges are *saga chaining* (adjacent beats of one ongoing series
glued together), never unrelated topics.

## Near-miss pairs (split suspects, cosine 0.34–0.35)

| pair | same story? |
|---|---|
| 1754 / 2368 (Le Pen) | **yes — split** |
| 1878 / 2373 (royals) | borderline — two gossip beats |
| 2312 / 2595 (World Cup) | no — different stories |
| 1961 / 2389 (French far right) | **yes — split** (analysis vs event, arguable) |
| 1828 / 1835 (diplomacy) | no — different stories |
| 1764 / 1811 (Brazil out) | **yes — split** (result vs reaction beat) |
| 2331 / 2604 (Nolan Wells) | **yes — split** |
| 2488 / 2496 (Wayanad) | **yes — split** |
| 1710 / 1804 (Khamenei funeral) | **yes — split** (and 1561 is a third fragment) |
| 1902 / 2181 (Balogun) | **yes — split** |

~6–7 of 10 near-misses are genuine fragments of an already-existing story.

## Conclusion — keep 0.35 for stories-v1.0

- **Precision is what corroboration needs, and precision is high**: a false
  merge would inflate a story's outlet count with unrelated coverage and
  poison the corroboration score; the audit found zero unrelated merges.
- **The observed error is fragmentation (under-merge)**, concentrated in
  multi-day sagas and follow-up beats. Its effect on WS-C is conservative:
  `outlet_count` becomes a **lower bound** on corroboration. Wrong direction
  for confidence inflation — the safe direction.
- Therefore the threshold stays at **0.35** and `corroboration-v1.0` builds
  on it. Any future improvement (e.g. a second-pass centroid merge over the
  0.30–0.35 band, or entity-anchored merging) is a **stories-v1.1** versioned
  change with its own audit — never an in-place tweak.

## Operational findings (feed into WS-C steps 2–4)

1. **Retention erases evidence**: 1,678 of 2,644 clusters no longer resolve
   member titles because their events were pruned. Corroboration must be
   computed (or member evidence snapshotted) at assignment time, not
   recomputed later from the events table.
2. **Duplicate feed echoes** inflate `member_count` (same title ingested
   twice); `outlet_count` is unaffected (distinct-source counting) and
   remains the right corroboration input.
3. `outlet_count` counts feeds, not owners — the independence registry
   (step 2) replaces it with distinct-owner counting.
