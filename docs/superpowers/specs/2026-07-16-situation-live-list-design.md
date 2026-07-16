# Situation panel v3 — live list + persistent chat (#439)

Date: 2026-07-16 · Status: approved (Basil, in-session)

## Problem

The Situation card (v2, #417) shows stale, truncated news and an amnesiac ask box:

1. `/stories/top` orders loudest-first (`outlet_count desc, member_count desc`) over a
   72 h window, so one big old story holds #1 for days. Recency is invisible.
2. Display hardcodes `FEATURED = 2` + `LIST_MAX = 6` (8 rows) although the fetch
   already returns 50.
3. `AskBox` keeps only the last Q&A inside the fixed footer — no history, no
   scrollback, no clear.

## Decisions (confirmed with Basil)

- **Ordering: latest activity first** — sort by `last_seen` desc. A story that gains
  a new article jumps back to the top (live-ticker feel).
- **Chat persistence: survives refresh** — sessionStorage; dies with the tab; clear
  button wipes it.
- **Frontend-only** — client-side sort of the existing 50-row fetch. No API change.

## Design

One scroll container; header and footer fixed:

```
┌─────────────────────────────┐
│ situation — the brain       │  header (fixed)
├─────────────────────────────┤
│ headline                    │ ▲
│ 1  12:05 story (newest)     │ │
│ …  all fetched rows (50),   │ │  one scroll container
│    click → gist + sources   │ │
│ ── chat ──────── [clear] ── │ │
│ you: …   brain: … [n]       │ ▼
├─────────────────────────────┤
│ system status line          │  footer (fixed)
│ [ask the brain…]  [ask]     │
└─────────────────────────────┘
```

### Stories

- Drop the featured/list split — uniform numbered rows for every fetched story,
  sorted `last_seen` desc.
- Row: HH:MM of `last_seen` + title + category chip. Click expands gist + outlet
  sources (gist moves into the expansion since featured cards are gone).
- SWR 60 s refresh re-sorts new activity to the top automatically.
- **Day markers** (added in review): a tiny `yesterday` / `wed 8 jul` label where
  a row starts an earlier day, so HH:MM never reads out of order across midnight.
- **Older stories collapsed** (Basil, in-session): default view shows only
  today + yesterday; a `+ N older stories` button reveals the rest of the 72 h
  window, `− hide older stories` collapses again. A quiet spell (nothing from
  today/yesterday) shows all rows rather than a blank card.
- **CardDeck `fill`** (found during verify): non-fill deck cards get an outer
  scroll wrapper that lets the panel grow unbounded and pushes the footer below
  the fold — the situation card must be `fill: true` and own its scroll.

### Chat

- `useBrainChat` hook: `messages: QA[]`, sessionStorage-backed (`brain-chat-v1`),
  corrupt-data guard on parse. Streaming updates the last message in place.
  `clear()` wipes state + storage.
- Transcript renders below the stories inside the scroll container, with a sticky
  mini-header holding the **clear** button.
- On submit the container scrolls to the bottom and stays pinned while streaming
  unless the user scrolls up.
- Input + system line stay in the fixed footer.
- Errors: stream failure → existing `fetchBrainAsk` fallback → "brain is offline"
  message stays in the transcript.

### Tests (vitest, `__tests__/`)

- Story sort fn (recency order, tie stability).
- Day markers (today unlabeled, yesterday, older-date labels).
- Recent/older split (boundary, all-older fallback, empty).
- Chat reducer: append / stream-delta / finalize / fail / clear / restore.
- sessionStorage serialize/parse with corrupt-data guard and size cap.

## Out of scope

- Backend ordering params or pagination.
- Cross-tab or long-term chat persistence.
- Any change to ask/streaming API contracts.
