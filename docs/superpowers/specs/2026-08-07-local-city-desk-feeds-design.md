# Local and city-desk feeds — design

Issue #805. Generalises #769 from Scotland to the tier #769 is an instance of,
and settles the first half of #803's scope question. The Reddit alternative was
measured in #804 and lost on every axis that decides it.

## The problem

Forty-four national and world desks produced six positioned rows for Edinburgh
in a week, five for Cairo, nine for Nairobi. Recent work — #717, #794, #796,
#800 — moved rows that were already stored, and moved them a long way, but
created no new story about any particular street. Ranking cannot retrieve what
the corpus does not hold.

## The shape of the fix

Ten entries in `app/sources/rss_feeds.json`. No new fetcher, no new module. The
registry has been JSON-driven since #158, so a feed is configuration.

## What was measured before choosing

Every candidate was fetched live on 2026-08-06/07. The rate is derived from the
span the returned items actually cover, never assumed.

| feed | items/day | owner | desk |
|---|---|---|---|
| STV News | 90.9 | stv | — |
| Herald Scotland | 81.1 | newsquest | — |
| Manchester Evening News, Greater Manchester | 68.5 | reach | GB |
| Glasgow Live, Glasgow | 26.3 | reach | GB |
| Edinburgh Live, Edinburgh | 23.6 | reach | GB |
| The Nation, Lahore | 18.9 | nawa-i-waqt | PK |
| The Scotsman | 17.6 | national-world | — |
| Capital FM Kenya | 14.7 | capital-group | — |
| BBC Manchester | 1.9 | bbc | GB |
| Standard Media Kenya | 0.9 | standard-group | — |

Rejected: Ahram Online, Nation Kenya, Nairobi News and Daily Times PK return
403; Egypt Today, The Star Kenya, Kenyans.co.ke and Standard's Nairobi county
feed return 404; Citizen Digital returns 400. Mada Masr, Egyptian Streets and
Al-Masry Al-Youm answer but are national rather than city. The BBC's Edinburgh
regional feed answers with 26 items spanning 322 days, which is a dead feed
that returns 200.

**Cairo has no city-desk RSS at all, and Nairobi gains a second national owner
rather than a street.** City desks exist in the UK and in Pakistan and not in
the two cities where #803 measured the worst coverage. Padding the list to look
complete would bury that, so it is written down instead.

## Three rules the entries follow

**`desk_country` only where the URL is structurally that place's section.**
Five feeds earn it: the Edinburgh, Glasgow, Greater Manchester, BBC Manchester
and Lahore desks. Every story in those feeds is about that country by
construction, which is the narrow claim `desk_country` exists to carry.

**No unmeasured `domestic_prior`.** STV, the Herald, the Scotsman, Capital FM
and the Standard are whole-outlet feeds — Scottish and Kenyan in practice. #796
fixed the bar at 80% domestic across a hand-labelled sample of at least twelve
of that feed's *own uncountried rows*, and a feed that has never run has no such
rows. They ship without a prior. A follow-up measures them after seven days.

**Owner ids, not slugs.** Edinburgh Live, Glasgow Live and the Manchester
Evening News are one company; BBC Manchester is the BBC. Three feeds carrying
one story are one teller, and letting them count as three is exactly the
independence inflation `app.stories.independence` was hardened against in #641.

## What is deliberately absent

No relevance filter. These feeds carry retail copy beside incidents. A filter
that raised the apparent signal share would be the comfortable number #798
exists to prevent; dedupe, the geo resolver and the story layer already decide
what survives, and #798's probe measures whether they did.

No new health check. `app.watchdog.check_sources` already alarms once a source
misses its cadence by the stale multiplier, which is the dead-feed case above.

## Verification

Each feed was parsed through the real `entry_to_event` transform with nothing
written to `events`:

| feed | entries | country | coords | bases |
|---|---|---|---|---|
| rss-edinburgh-live | 25 | 25 | 18 | city 17 · desk 5 · term 3 |
| rss-glasgow-live | 25 | 25 | 17 | city 16 · term 4 · desk 5 |
| rss-nation-lahore | 100 | 100 | 88 | city 69 · term 25 · desk 6 |
| rss-men-manchester | 25 | 25 | 9 | city 9 · desk 16 |
| rss-bbc-manchester | 23 | 23 | 12 | city 11 · desk 8 · term 4 |
| rss-herald-scotland | 50 | 39 | 27 | city 18 · term 16 · region 5 · none 11 |
| rss-stv-news | 50 | 32 | 21 | none 17 · city 15 · term 12 |
| rss-scotsman | 37 | 18 | 12 | none 18 · city 9 · term 6 |
| rss-capital-fm-kenya | 10 | 6 | 2 | none 4 · term 4 · city 2 |
| rss-standard-kenya | 30 | 8 | 3 | none 21 · term 5 · city 3 |

One Edinburgh Live pull yields 18 positioned Edinburgh rows against six for the
whole of the measured week.

Two defects surfaced by the dry run belong to the resolver, not to these
entries, and are left for their own issues rather than patched here:

- STV's *Amanda Knox says criticism of Edinburgh Fringe show is 'deeply
  uninformed'* resolves to `US`.
- The Scotsman's *Edinburgh festivals to create 'significant' new event*
  is pinned at 53.50, -2.25 — Manchester — on a `city` basis, which is the
  shape of #773.

**Recall improvement is not claimed on merge.** It cannot be: these feeds have
never run. Once they have, `app.audit.city_probe` over Edinburgh, Glasgow,
Manchester and Lahore is the check, and it is allowed to disappoint.
