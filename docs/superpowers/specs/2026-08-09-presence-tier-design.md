# Presence: things that are somewhere now — design

## What this is for, honestly

This is capacity, not a repair. The issue that prompted it argued from three
premises and two of them did not survive being checked against the running
system:

- **ADS-B is not a firehose.** #496 already fixed that. The fetcher aggregates
  to one upserted row per country per hour with no coordinates, which is also
  why it is not on the map — a country aggregate has no position.
- **`fix/event-buffer-aviation-flood` is a dead branch**, over a hundred
  thousand deletions behind `main`. It is not evidence of a live problem.
- **The bulk is elsewhere.** Measured on the running database: 2,037,246 rows
  across 2.7 GB of a 30 GB cap, of which `nasa-firms` is 1,748,438 — 86%.
  FIRMS is legitimately evidence; `composite/aggregation.py` reads it as
  `WILDFIRE_SOURCE`.

So there is no storage crisis to solve. What is missing is a *place to put*
data that should never be stored, so that adding such a sensor is a
configuration change rather than an architectural argument each time.

The concrete first sensor makes it worth doing now: military aircraft and
aircraft squawking an emergency. Not all traffic — the ones worth knowing
about.

## The boundary

One question decides which side anything falls on:

> **Can this be cited later?**

**Evidence** is a claim that something happened. It is persisted, graded,
retained, audited, and available for a story to point at. FIRMS is evidence.
So is every RSS desk, ACLED row and earthquake.

**Presence** is where something *is, right now*. Fetched, drawn, discarded. No
row, no severity, no country attribution, no story membership, no retention
entry. A military aircraft's position twenty minutes ago supports no argument
and answers no question, which is exactly why it must not be kept.

The distinction is not about volume. It is about whether the datum is a claim.

## What v1 carries

Two lists from one publisher, merged:

- **Military** — aircraft the aggregator flags as military. Measured live: 106
  airborne worldwide, 69 of them with a position, 42 KB for the lot.
- **Emergency** — anything squawking 7500 (hijack), 7600 (radio failure) or
  7700 (general emergency). Measured live: zero, on all three. That is the
  point. A non-zero 7700 is a real event rather than background traffic.

**The whole world fits in one fetch.** There is no viewport parameter, no box
snapping and no area guard, because a hundred aircraft is not worth paging.
This is a large simplification over the first draft of this design, and it
exists because the numbers were measured before the design was written.

Aircraft with no position are dropped. There is nothing to draw.

**Every other field is optional, and the counts are not close to full.** Of 66
positioned aircraft in one measured sample: `track` on 62, type on 65,
registration on 65, callsign on 58, squawk on 56. Direction comes from `track`
— the direction of travel over the ground — because `true_heading` was present
on only 5 of 66 and a rendering that needed it would be blank most of the time.

An aircraft with no track is drawn without rotation rather than pointing north,
because north is a claim and no-rotation is not. The same rule applies to every
missing label: absent is shown as absent.

## What v1 does not carry

**Ships and navy.** There is no keyless live source: `aisstream.io` answers 400
without a key, Global Fishing Watch 401 without a token, the Danish open feed
was unreachable, and the US archive is historical files rather than a live
service. The deeper problem is that warships routinely do not transmit AIS at
all, so the vessels most worth seeing are precisely the ones absent from every
feed. Adding a regional civilian feed would put ships in Nordic waters and
nowhere else, which reads as a fact about the world rather than a fact about
coverage.

**Privacy-enrolled aircraft.** The same publisher exposes lists of aircraft
whose owners have asked to be displayed with limited data or an anonymised
address. Watching state military movements is ordinary open-source
intelligence. Building a screen whose purpose is to surface aircraft that
asked not to be surfaced is a different thing, mostly concerns private owners
rather than anything strategic, and is not what this is for.

## Licence, and why it reinforces the design

The confirmed source publishes under **ODbL 1.0**: attribution required,
share-alike on adapted databases that are publicly used.

Because presence data is never stored and never redistributed, the map is a
Produced Work rather than an adapted database. Produced Works require the
attribution notice and do not trigger share-alike. **Storing this data is what
would create a licence problem**, which is a pleasing argument for a design
that already refuses to.

Two mirror endpoints return identical data and would make good fallbacks, but
both refused a request to read their terms. The registry supports mirrors as a
one-line configuration; only the source whose licence has actually been read
ships enabled. A fallback nobody can legally confirm is not a fallback.

`NOTICE.md` gains the source, as the working agreement requires.

## Server

A new package, `app/presence/`, deliberately sealed:

| File | Responsibility |
| --- | --- |
| `registry.py` | One entry per presence source: id, label, endpoints in priority order, cache TTL |
| `aircraft.py` | Fetch the two lists, merge, dedupe, normalise |
| route in `app/api.py` | `GET /presence/aircraft`, delegating immediately |

Merging is by ICAO hex, because an aircraft can legitimately be on both lists
at once — a military aircraft squawking 7700 is one aircraft and the more
urgent of its two reasons for appearing wins.

Cache is in-process with a ~30 s TTL. No table, no migration, no retention
entry, no watchdog registration, no audit expectation.

```
{
  "fetched_at": "2026-08-09T14:02:11Z",
  "count": 69,
  "aircraft": [
    {
      "hex": "ae266c", "callsign": "C6518", "type": "AS65",
      "registration": "6518", "lat": 20.646, "lon": -156.618,
      "track": 214.0, "alt_ft": 2950, "speed_kt": 72.8,
      "kind": "military", "squawk": "2303"
    }
  ],
  "degraded": false
}
```

`degraded` is true when no endpoint answered. The layer then says so instead of
showing the last positions it happened to have.

### The boundary is enforced, not documented

`app/presence/` must not import `app.db_models`, and a test asserts it. A
boundary that lives only in a paragraph is a boundary that erodes the first
time somebody needs a quick join.

## Frontend

- `stores/presenceStore.ts` — which presence layers are on
- `lib/presence.ts` — pure helpers, tested without a network
- `MapPane` — polls every 30 s **only while the layer is on and the tab is
  focused**; a background tab must not spend somebody else's bandwidth
- `FilterRail` — toggles reading **Military air** and **Emergency**, beside the
  satellite ones from #875

Military renders as a small dim mark rotated to its heading. Emergency renders
distinctly and louder, because a 7700 is not background traffic.

Hover shows type, registration and altitude. **Nothing is clickable.** There is
no detail card and no place-screen entry: presence must look and behave
differently from evidence, or the distinction survives only in the code.

Presence aircraft are excluded from event counts, source filters, clustering,
the situation list and every existing selection path. They are not events.

## The three honesty rules

1. **The layer states its own age** — "as of 8s ago". A live layer that does
   not say when it last heard anything is indistinguishable from a frozen one.
2. **Failure is visible.** When no endpoint answers, the layer says so and
   draws nothing. Stale dots presented as current are worse than an empty map.
3. **Presence hides when the scrubber leaves "now", and says why.** Nothing is
   stored, so there is no past to show. A live layer left visible over a
   three-week-old map would be the most convincing lie this console could
   tell.

## Tests

Server, with a stubbed client and a recorded payload:

- military and emergency lists merge, deduped by hex, emergency winning
- aircraft without a position are dropped
- the first endpoint failing falls through to the next
- every endpoint failing returns `degraded` rather than raising
- a second call inside the TTL makes no upstream request
- `app/presence/` imports no database model

Frontend:

- polling starts only when the layer is on and the document is visible
- the layer hides when the time window is not "now"

The repository has no browser automation, so the marks, the hover label and the
emergency styling ship unverified by machine and need a human to look.

## Out of scope

- Ships, AIS, radio, mesh
- Historical playback of presence data
- Viewport scoping — unnecessary at this volume
- #874's imperative `setData`, which follows this once there is a firehose to
  justify it
- Retiring the existing aggregated `opensky-adsb` source. It is 78,527 rows
  that feed no score and appear on no screen, which makes it a real candidate
  for deletion — but tangling "remove a source" into "add a tier" makes both
  harder to review. Separate decision, separate issue.
