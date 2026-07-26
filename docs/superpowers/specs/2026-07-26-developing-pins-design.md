# Situation card — pinned developing stories (#449)

Date: 2026-07-26 · Status: approved (Basil, in-session)

## Problem

The Situation card's most valuable real estate — the top of the list — is ordered by
`last_seen` desc (#439). Whatever outlet published most recently sits highest, so a
sports result outranks a widening war. The card's claim is "the answer, not a hunt",
and it currently delivers a ticker.

#449 asks for 2–3 pinned developing stories above the list: multi-day international
stories still gathering coverage.

## The rule in the issue body does not work

The body proposes `first_seen >= 24h` + fresh `last_seen` + high `outlet_count`. Run
against live data on 2026-07-26 that pins:

| candidate | outlets | verdict |
|---|---:|---|
| Seven Palestinians arrested after Israeli assaulted, West Bank | 13 | real |
| Joy in Greece as Mount Olympus joins Unesco heritage list | 12 | **junk** |
| 'Can't go unanswered': Iran threatens response to Ukraine attack | 11 | real |
| India's Cockroach Janta party protest victory | 8 | **junk** |
| From stage 6 onwards, Pogacar 'never let go' during Tour de France | 7 | **junk** |

Adding velocity (members added in the last 12 h) does not repair it — Unesco ranks
second and "Who is India's new education minister" ranks sixth.

Two further measurements shaped the design:

- **`story_gist.category` cannot be the filter.** Mount Olympus is labelled
  `disaster` / `escalating=yes`; Typhoon Noul and the Iran threat are both `other` /
  `no`. 79 % of all gists are `other`. The 1.5b labels invert on exactly the rows
  that matter, and only 160 of 291 fresh stories carry a gist at all.
- **Severity discriminates.** Pogacar 0.3 and the education minister 0.3 fall below
  any useful floor; the Russian/Ukrainian strikes score 0.8 and the West Bank arrests
  0.6. This is the signal #591/#597 is repairing.

## Decisions (confirmed with Basil)

- **Selector: severity + country spread + velocity + age.** Deterministic, no LLM.
- **Corroboration: shown, never gated.** A widely-covered story with few independent
  owners stays pinned and displays its score — flagging that is the point of the
  system (#363/#365, #641). Gating would hide it.
- **Placement: own block under the brain headline.** The brain's `narrative.headline`
  keeps the h2; pinned rows sit directly beneath it as a labelled `DEVELOPING` block,
  above the activity list.
- **Empty state: the block disappears.** Nothing qualifying means nothing is
  developing, which is information. Thresholds are never relaxed to fill the slot —
  a slot that pins the wrong thing is worse than no slot.
- **API: a new `GET /stories/developing`.** Keeps `/stories/top` untouched and makes
  the rule testable in isolation.

## Design

### 1. Selection — `app/stories/developing.py`

`select_developing(session, limit=3) -> list[dict]`.

Candidate set: stories whose `last_seen` is within 6 h and whose `first_seen` is at
least 24 h old. Each candidate is aggregated over its members
(`story_members` → `events`), then four gates apply:

| gate | threshold | rejects |
|---|---|---|
| `max(events.severity)` across members | `>= 0.6` | Pogacar 0.3, education minister 0.3, Unesco 0.5 |
| `count(distinct events.country)` | `>= 3` | single-country domestic politics |
| members with `added_at` inside 12 h | `>= 1` | stories that stopped gathering |
| `now() - first_seen` | `>= 24 h` | today's flashes; "multi-day" is the definition |

Survivors rank by velocity desc, then country spread desc, then `outlet_count` desc.
The first `limit` rows are returned.

Thresholds are module constants. Their docstring records that they were calibrated
while news severity coverage stood at ~23.3k of ~25.9k rows, and that they must be
re-checked at full coverage.

On live data the gates return exactly four candidates, all legitimate:

| story | max_sev | countries | new/12 h | age |
|---|---:|---:|---:|---:|
| Seven Palestinians arrested, West Bank | 0.6 | 3 | 17 | 144 h |
| Romania summons Russian envoy, third drone downed | 0.6 | 3 | 7 | 108 h |
| Typhoon Noul batters Southeast China | 0.6 | 3 | 7 | 66 h |
| Iran threatens response to Ukraine attack | 0.6 | 4 | 6 | 25 h |

### 2. Endpoint — `GET /stories/developing?limit=3`

Rows carry the `/stories/top` shape (id, title, first/last seen, member/outlet/owner
counts, corroboration score and components, sensor checks, gist fields) plus:

```
"pin_reasons": {
  "max_severity": 0.6,
  "countries": 4,
  "new_members_12h": 6,
  "age_hours": 25
}
```

`pin_reasons` exists so the UI can justify a pin rather than assert it. An empty
list is a normal 200 response.

### 3. Frontend — `DevelopingBlock` in `SituationPanel`

- `fetchDevelopingStories` joins `lib/analytics.ts` beside `fetchTopStories`.
- Own SWR key, refresh interval matching the existing `STORIES_REFRESH_MS` (60 s).
- Renders between the brain h2 and the activity list: a `DEVELOPING` label, one row
  per pinned story showing title, outlet and country counts, corroboration score and
  owner count, then a divider.
- Rows open the detail pop-out through the existing `useStoryDetailStore`, exactly as
  `StoryLine` does.
- Pinned ids are filtered out of the list below, so no story renders twice.
- Zero rows → the component returns `null` and the card is byte-identical to today.

```
┌─ situation ────────────────────────┐
│ Iran-Ukraine exchange widens as    │  ← brain h2, unchanged
│ Romania downs third drone          │
│                                    │
│ DEVELOPING                         │
│ ● Iran threatens response to       │
│   Ukraine attack  11 outlets 4co   │
│   corrob 0.62 · 11 owners          │
│ ● Romania summons Russian envoy    │
│   8 outlets 3co · corrob 0.55      │
│ ──────────────────────────────     │
│ 1  21:14  Typhoon Noul batters…    │  ← activity list
│ 2  20:58  UN chief calls for…      │
└────────────────────────────────────┘
```

### 4. Tests

`tests/test_stories_developing.py`, against seeded stories:

- each gate rejects in isolation — low severity, two countries, no member added in
  12 h, `first_seen` under 24 h
- ranking order: velocity, then country spread, then outlet count
- `limit` respected
- empty list when nothing qualifies
- `pin_reasons` populated and matching the aggregates

Frontend (`osint-frontend/__tests__`): the pinned-id filter removes pinned stories
from the activity list, and zero pinned rows renders nothing.

## Known limitation

The block's quality rides on news severity being correct. The #597 regrade is
still running; at 25,433 of ~25,855 rows (98.4% coverage, ~400 remaining),
thresholds were re-checked and confirmed unchanged. The measured false negative
persists: **Fires in France** (42,000 hectares, 220,000 evacuated) fails at
`max_sev 0.5` / `ctry 2` because only 15 of its 22 members carry the new grade.

A second measured limitation: 69.9% of story members (19,207 of 27,486) carry
NULL `events.country`, making the country-spread gate the binding ceiling on
which stories can qualify. This is partly geocoding coverage rather than stories
being genuinely single-country, making the selector conservative by design —
it prefers pinning nothing to pinning incorrectly. Worth its own follow-up issue
rather than a threshold change here.

Cluster impurity is a third, separate source of error: story 16977 mixes the Unesco
listing with Israeli bombardment of Tyre, which is why it reaches 0.5 at all. Out of
scope here; it belongs to clustering quality.
