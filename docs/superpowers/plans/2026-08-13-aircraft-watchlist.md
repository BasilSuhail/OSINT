# Aircraft roles and a watchlist

**Goal:** Make the live aircraft layer answer "where is *that* aircraft" as well as "what is in the air over there" (issue #954).

**Architecture:** A new `app/presence/watchlist.py` holds two pure pieces — a role read from the ICAO type designator, and a watchlist keyed by hex and registration loaded from a path in the environment. `app/presence/aircraft.py` gains one extra upstream call that asks for the watchlist's own identifiers directly, so a civil-registered airframe is reachable even though it is not in the military list. Rows carry `role`, `watch` and `airborne_since`. The frontend gets a rail switch under the live-aircraft row, a highlighted mark, and the label on the card.

**Tech stack:** Python 3.14, httpx, pytest, ruff on the backend. TypeScript, React 19, maplibre, vitest on the frontend. No new dependencies either side.

## Global constraints

- **The watchlist is never committed.** It carries identifiers and office labels and is loaded from `PRESENCE_WATCHLIST_PATH`. The repository ships an example with office labels only — no personal names anywhere, in the file, the tests, the commit or the PR.
- **Presence stays unstored (#873).** `airborne_since` is what this process has observed since it started. It lives in memory, it is described on screen as what the console has seen, and it does not survive a restart. Nothing here goes near the database.
- **Coverage is receiver coverage.** No copy anywhere may imply the layer sees everything flying. What it shows is what the aggregator's receivers heard.
- `ruff format --check .` and `ruff check .` must both pass; backend CI runs both.
- Targeted tests during implementation; the full suite belongs to CI.
- 1 issue → 1 branch → 1 PR → 1 commit. Issue #954, branch `feat/954-aircraft-watchlist`.
- No attribution trailers in the commit or the PR body.

## What is already known

Measured against the live aggregator on 2026-08-13, before any code was written:

| Question | Answer |
|---|---|
| Military aircraft worldwide, one sample | 457 |
| Of those, carrying a position | roughly a third |
| Type designator present | 421 of 457 |
| Registration present | 421 of 457 |
| `/v2/hex/{a,b,c}` with a comma list | works — returned 3 for 3 |
| `/v2/reg/{a,b}` with a comma list | works — returned 2 for 2 |
| A designator query for an aircraft not airborne | empty, not an error |

The comma-list result is what makes the watchlist affordable: one request covers the whole list, whatever its length, and the answer contains only what is currently flying.

## File structure

| File | Responsibility |
|---|---|
| `app/presence/watchlist.py` (create) | `role_for()` over the type designator; `load_watchlist()` and `match()` over hex and registration; the in-memory airborne ledger. |
| `app/presence/watchlist.example.json` (create) | Shape documentation. Office labels only. |
| `app/presence/aircraft.py` (modify) | One extra upstream call for the watchlist's identifiers; `role`, `watch` and `airborne_since` on every row; watched rows merged with the military and distress lists. |
| `env.example` (modify) | `PRESENCE_WATCHLIST_PATH`, commented, empty by default. |
| `tests/test_presence_watchlist.py` (create) | Roles, loading, matching, the ledger, and the merge. |
| `osint-frontend/lib/presence.ts` (modify) | `role`, `watch`, `airborne_since` on `PresenceAircraft`; a label for the role; "airborne since" phrasing. |
| `osint-frontend/stores/presenceStore.ts` (modify) | A second switch, `watchlist`. |
| `osint-frontend/components/FilterRail.tsx` (modify) | The row under live aircraft. |
| `osint-frontend/components/MapPane.tsx` (modify) | Watched marks drawn to stand out; both switches honoured. |
| `osint-frontend/components/panels/AircraftDetailCard.tsx` (modify) | Role, watch label, airborne-since, and what that phrase means. |

## Tasks

### 1. Roles from the designator

- [ ] `role_for(type_code)` returns one of `tanker`, `isr`, `fighter`, `transport`, `rotorcraft`, `trainer`, `other`.
- [ ] Rotorcraft is decided by the same families the frontend silhouette uses, so the two never disagree about the same aircraft.
- [ ] Tests name the designators measured in the live sample rather than famous types.

### 2. The watchlist

- [ ] `load_watchlist(path)` reads a JSON array of `{hex?, registration?, label, category}` and returns a lookup keyed by upper-cased hex and registration. A missing path is an empty watchlist, not an error — the layer must work with no watchlist at all.
- [ ] A malformed entry is skipped, and the rest of the file still loads.
- [ ] `match(row)` prefers hex, falls back to registration.

### 3. The extra call

- [ ] When the watchlist is non-empty, one `/v2/hex/` request and one `/v2/reg/` request, each with a comma-joined list, batched so no URL grows unbounded.
- [ ] Failure is partial in the way the existing code already treats a refused squawk query: the military list survives it, and `degraded` says so.
- [ ] A watched aircraft that is also in the military list is one row, and distress still wins the kind.

### 4. The airborne ledger

- [ ] For watched rows only: first time seen with an altitude that is not "on ground", remember when. Seen again, keep the original time. Absent for longer than a grace period, forget it.
- [ ] Exposed as `airborne_since`, an ISO timestamp, absent when unknown.
- [ ] Never persisted. A test asserts that clearing the module's state clears it.

### 5. The rail row and the map

- [ ] A `watchlist` switch under the live-aircraft row, with the same "live only" disabling the aircraft row already has.
- [ ] A watched mark reads as watched at a glance without becoming the loudest thing on a map that also draws disasters.
- [ ] The card says the label, the role, and how long the console has seen it airborne — with the words that make clear that is this session's observation and not a flight record.

## What this deliberately does not do

- No alerting, no notification, no "left the ground" event. The ledger is a label on a card in this pass.
- No stored track and no history. Presence remains a live layer with no past.
- No owner resolution, no registry lookups, no names. The watchlist says what an airframe *is for*; who is aboard is not a question this console answers.
