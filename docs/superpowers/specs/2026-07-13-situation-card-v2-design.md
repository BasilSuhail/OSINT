# Situation card v2 — a live briefing

**Issue:** #417
**Status:** design approved, spec under review
**Scope:** frontend-only (`osint-frontend`), no backend/API change.

---

## 1. Problem

The Situation card shows one synthesized narrative (a single headline + a few
sentences). With many stories breaking worldwide, it should surface the **latest loud
stories together** — each readable at a glance — with the brain's read on top and the
status + ask box pinned at the bottom.

## 2. Reuse (nothing new on the backend)

- `/brain/narrative/latest` (`fetchBrainNarrative`) → headline, system line, model, as-of.
- `/stories/top` (`fetchTopStories`) → stories, loudest first; already carries the
  Phase-3 `gist / category / escalating`.
- `/stories/{id}/members` (`fetchStoryMembers`) → a story's outlet sources, on demand.
- `/brain/ask` (`fetchBrainAsk`) → the existing ask box.

## 3. Layout (top → bottom)

`SituationPanel` becomes a fixed-height flex column: a header, a **scrollable middle**,
and a **fixed footer** (status + ask box) that stays visible while the middle scrolls.

1. **Header** (fixed) — `SITUATION — THE BRAIN` + model badge. Unchanged.
2. **Scrollable middle** (`flex-1 min-h-0 overflow-y-auto`):
   - **Stale banner** — the existing "brain resting" message when the narrative is
     absent/stale.
   - **Headline** — `narrative.headline`, the one-line read of the moment.
   - **2 featured stories** — numbered `1`, `2`. Each: the number, the story title,
     its `gist`, and a tag chip (`category`, with `↑` when `escalating === "yes"`).
     Clicking the row toggles an inline expansion showing its outlet sources
     (`fetchStoryMembers`) — outlet · owner · headline per member.
   - **More stories** — a compact numbered list (`3`, `4`, `5`…): number + title + tag
     chip, each row clickable to expand the same way. Show up to ~6.
3. **Fixed footer** (`shrink-0`, border-top):
   - **Status line** — `narrative.system` + the as-of time.
   - **Ask box** — the existing `AskBox` (POST `/brain/ask`, last few answers in
     component state). Now lives in the fixed footer so it is always visible.

If there are no stories yet, the middle shows just the headline/stale state; the footer
still renders. Absent gist on a story → the row shows title + tag only (no gist line).

## 4. State + data flow

- `fetchBrainNarrative` via SWR (5-min refresh) — as today.
- `fetchTopStories(72, 50)` via SWR (same ~60s refresh the Stories card uses) → sort is
  already loudest-first from the API; take `[0,1]` as featured and `[2..7]` as the list.
- Expanded story ids tracked in a `Set<string>` in component state; clicking toggles.
  Each expanded story fetches its members via SWR keyed by `["situation-members", id]`
  (cached, so re-expanding is instant) — the same pattern the Stories card uses.
- Numbering is the story's 1-based position across featured + list.

## 5. Non-goals

No backend change, no new narrative payload, no re-ranking of stories (reuse the API's
loudness order), no multi-turn Q&A, no tag filtering. Those stay their own issues.

## 6. Verification

The repo has no React component test harness (vitest covers `lib` functions only), so:

- `pnpm exec tsc --noEmit` clean (types across the new panel).
- Existing `pnpm test` suite still green (no lib changes expected; if a small helper is
  extracted to `lib`, add a `.mts` test for it).
- **Live visual check** against the running stack: load the dashboard, open the Situation
  card, confirm headline + 2 featured stories with gists + the numbered list + a working
  expand + the sticky footer/ask box, and that the ask box stays put while scrolling.

## 7. Deliverables

- [ ] `SituationPanel.tsx` reworked: header / scrollable stories / fixed footer + ask.
- [ ] numbered, clickable story rows with tag chips + inline member expansion.
- [ ] sticky status footer (narrative system + as-of) and sticky ask box.
- [ ] `tsc` clean + `pnpm test` green + live visual confirmation.
- [ ] progress note on #417.
