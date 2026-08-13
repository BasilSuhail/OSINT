# Vessels on the map

**Goal:** A live vessel layer with the categories AIS already transmits, its own filter group, and a watchlist — part two of issue #954.

**Architecture:** `app/presence/vessels.py` fetches positions and static data from an open national AIS feed, joins them by MMSI, and caches with a TTL the way `app/presence/aircraft.py` already does. `app/presence/vessel_types.py` turns the transmitted ship-type code into a category. A `/presence/vessels` endpoint mirrors `/presence/aircraft`. The frontend gets a glyph set drawn in the repository, a rail group with one switch per category, and copy that names the sea areas covered.

**Tech stack:** Python 3.14, httpx, pytest, ruff. TypeScript, React 19, maplibre, vitest. No new dependencies.

## Global constraints

- **Unstored, uncitable, live only.** Same rule as aircraft (#873): nothing persisted, the poll stops when the tab is hidden or the scrubber leaves "now", and there is no history to scrub back to.
- **Coverage is stated, not implied.** The open feeds are terrestrial. The layer draws the Baltic densely and the mid-Atlantic not at all, and the copy has to say why, or the empty ocean reads as a claim about the ocean.
- **No owners, no names of people.** A watchlist is keyed by MMSI and labelled by what a vessel is for. Operational data, loaded from the environment, never committed.
- `ruff format --check .` and `ruff check .` both pass. Targeted tests while building.
- 1 issue → 1 branch → 1 PR → 1 commit. Issue #954, part two.

## Measured before designing (2026-08-13)

| Probe | Result |
|---|---|
| `meri.digitraffic.fi/api/ais/v1/locations` | 1,261 vessels, no key, no account |
| `meri.digitraffic.fi/api/ais/v1/vessels` | name, call sign, IMO, ship type, destination, draught |
| Global Fishing Watch v3 | `401 invalid token` — free token, registration, licence to read |
| Norwegian live AIS | `401` — free account, OAuth |
| Danish AIS mirror | no answer; historical dumps only |

Position rows carry `mmsi`, `sog`, `cog`, `heading`, `navStat`, `posAcc`, and a timestamp. Static rows carry `name`, `shipType`, `destination`, `draught`, `imo`, `callSign`. The join key is `mmsi` and both endpoints are one request each.

## File structure

| File | Responsibility |
|---|---|
| `app/presence/vessel_types.py` (create) | AIS ship-type code to category, pure. 30 fishing, 36-37 pleasure, 60-69 passenger, 70-79 cargo, 80-89 tanker, the rest other. |
| `app/presence/vessels.py` (create) | Two requests, join by MMSI, normalise, TTL cache, partial degradation. |
| `app/presence/registry.py` (modify) | The source, its endpoints, its TTL and its attribution. |
| `app/api.py` (modify) | `/presence/vessels`. |
| `tests/test_presence_vessels.py` (create) | Types, the join, absence, degradation. |
| `osint-frontend/lib/vessels.ts` (modify/create) | Types, category labels, "as of" phrasing. |
| `osint-frontend/components/VesselGlyph.tsx` (create) | Hull outline per category, rotated only when a heading was sent. |
| `osint-frontend/stores/presenceStore.ts` (modify) | A switch per category plus a watchlist switch. |
| `osint-frontend/components/FilterRail.tsx` (modify) | The new group. |
| `osint-frontend/components/MapPane.tsx` (modify) | Draw them, open them. |

## Tasks

### 1. Categories from the wire

- [ ] `category_for(ship_type)` over the transmitted code. The category is read, never guessed: an absent or reserved code is `other`, not cargo.
- [ ] Tests use codes present in the live sample.

### 2. Fetch and join

- [ ] Positions and static data in one refresh, joined by MMSI. A vessel with a position and no static row is still drawn — it is a real vessel — with no name and no category.
- [ ] A static row with no position is dropped: there is nothing to draw.
- [ ] Partial failure stays partial, and the response says `degraded`, the way the aircraft feed already does.
- [ ] TTL cache, and an empty degraded answer is never cached.

### 3. On the map

- [ ] A hull outline per category, drawn in the repository. Rotated by `heading`, or by `cog` when heading is absent, and not at all when neither was sent.
- [ ] Stopped and at-anchor read differently from under way, because `navStat` and `sog` say so for free.
- [ ] Clicking one says what it is, where it says it is going, and who reported it.

### 4. The filter group

- [ ] One switch per category, any combination, plus a watchlist switch — the disaster rows are the model.
- [ ] The group states the covered sea areas, so an empty ocean is not read as an empty ocean.

### 5. The watchlist

- [ ] Keyed by MMSI, labelled by what the vessel is for, loaded from the environment, never committed.
- [ ] Drawn to stand out without outshouting a disaster mark.

## A later part, not this one

Global Fishing Watch is worth a token, but it is aggregated effort on a grid with a latency in days plus derived events, not live positions. It belongs in its own layer with its own date stamp. Merging it into a live layer would present days-old aggregate as current, which is the one thing a live layer must never do. Its licence is read before any code is written.

## What this deliberately does not do

No history, no stored tracks, no encounter or loitering detection of our own, no owner resolution, no satellite AIS, no paid feed.
