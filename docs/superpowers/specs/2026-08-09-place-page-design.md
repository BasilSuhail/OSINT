# Right-click a point, get the place — design

## The problem

The console can already describe a country: `CountrySidePanel` renders a flag,
the composite score, domain z-bars and recent events. Almost nobody sees it.
The only way in is the ISO chip inside an event detail card, so you have to
already have found an event in a country before the console will tell you
anything about the country.

Meanwhile the map answers a different question well — left-click draws a radius
and lists what happened inside it — and answers "what am I looking at, and what
is it" not at all.

This adds that answer. Right-click anywhere on Earth and the left column gains
a page describing the place under the cursor: who runs it, how big it is, two
sentences of background, and the most recent low-cloud Sentinel-2 photograph of
that exact spot.

## The word

The page is called **place**, in code and on screen. Not "dossier" — a word
that means a folder of collected papers on a subject, and that nobody says out
loud. Not "country" either, because right-clicking the Atlantic is a legitimate
thing to do and the answer there is a photograph of open water with no country
attached. Place covers both.

Deck titles are one plain word each — situation, world, selection, scoreboard —
and this joins them.

## What the page looks like

```
┌────────────────────────────────────┐
│ 🇬🇧  United Kingdom          GB  ✕ │
│      Constitutional monarchy       │
├────────────────────────────────────┤
│ Head of state          —           │
│ Head of government     —           │
│ Capital                —           │
│ Population             —           │
│ Languages              —           │
│ Currency               —           │
│ Area                   —           │
├────────────────────────────────────┤
│ Two sentences of summary text, no  │
│ more than that.        Read more → │
├────────────────────────────────────┤
│                                    │
│      [ Sentinel-2  512 × 512 ]     │
│                                    │
├────────────────────────────────────┤
│ 30 Jul 2026 · 28% cloud · 10 m     │
│ Full resolution →                  │
├────────────────────────────────────┤
│ Copernicus · Wikipedia · Wikidata  │
╞════════════════════════════════════╡
│ composite score                    │
│ domain z-bars                      │
│ recent events                      │
│        (existing CountrySidePanel) │
└────────────────────────────────────┘
```

Facts before photograph. Who runs a place and how many people live there is the
question a right-click is asking; the picture is evidence, not the headline.

The double rule is a real divider. Above it, what the place *is* — slow facts
that change on the scale of years. Below it, what is *happening* there — the
existing score, z-bars and event list, unchanged. One right-click answers both
questions, and the buried panel stops being buried.

Nothing sits in two columns. Every row is a label and a value, one per line,
and the page scrolls rather than compressing. A long page is fine; a crowded
one is not.

Blocks the server could not fill render as a single quiet "unavailable" line
rather than disappearing. A block that silently vanishes teaches the reader the
console has nothing to say, when what happened is that a third-party server was
slow.

Over ocean the identity row reads as open water with the coordinates, the
country facts are absent, the photograph is still there, and everything below
the divider is gone — scores and country events have nothing to key on.

## Interaction

**Left-click is untouched.** It keeps drawing the local radius and building the
selection page. That behaviour is well-worn and this feature does not disturb
it.

**Right-click opens the place page.** `MapGL` gains `onContextMenu`; the
handler calls `preventDefault()` on the native event so the browser menu never
appears, takes `e.lngLat`, and opens the page.

## Where the page sits

The deck's left column is currently `situation`, `world`, then `selection` when
a map click makes it, then `scoreboard` when something has been graded.

A place is not a selection. Putting it on the selection page would mean every
right-click destroyed whatever list the reader had built with a left-click —
the precise failure `SelectionPanel` was created to end.

So `place` becomes a fourth page key, appended after `selection` and before
`scoreboard`. Appended, never inserted: screens 1 and 2 must never move.

```
export type DeckPageKey = "situation" | "world" | "selection" | "place" | "scoreboard"

export interface DeckState {
  selection: boolean
  place: boolean
  scoreboard: boolean
}
```

This adds a screen to the original list. The left column has always been the
numbered screens, and `place` becomes another one of them — screen 4 when a
selection exists, screen 3 when it does not.

The pop-up is not on that list and never was. It is a pop-up: it appears over
what you were reading and goes away again. Numbering it was the confusion that
#843–#853 spent five pull requests undoing, and this design does not reopen it.
`lib/screenRule.test.mts` is where that distinction is written down, so its
comment block gets the fourth screen added to the list and the pop-up left out
of the numbering.

`lib/screenRule.test.mts` grows cases for the new key: `place` appears only
when a place is open, always sits after `selection`, and never displaces
screens 1 and 2 in any combination of the three flags.

`SplitLayout` pushes the card between the existing two blocks, and its
dev-mode drift check picks up the new flag for free.

### Store

New `stores/placeStore.ts`:

```
interface OpenPlace { lat: number; lon: number; iso: string | null }
open(lat: number, lon: number)
close()
```

The point is what the reader picked, so the point is what the store holds; the
ISO arrives with the server's answer and may legitimately be null.

`RightPaneEntity` **loses** its `country` variant. Its kinds become `event`,
`cluster` and `area` — the three things a map selection can be. Two places
follow. `SelectionPanel` loses its country branch and handles three kinds.
`CardDeck`'s entity token loses its country case and gains a second effect for
the place page, keyed on the coordinates, so right-clicking a second spot while
the page is open still moves the deck.

The ISO chip inside `EventDetailCard` opens the place page for that country
without a point. Every text block renders; the photograph block is absent
rather than invented from a centroid.

## Server

One route, `GET /geo/place?lat=&lon=`, thin in `app/api.py`, with the work in a
new `app/enrichment/place_screen.py`. The module follows the house pattern from
`app/enrichment/article_title.py`: a plain function with an injectable
`httpx.Client`, so tests never touch the network.

### Sources

| Block | Service | Key required |
| --- | --- | --- |
| capital, population, languages, currencies, area | RestCountries | no |
| government type, head of state, head of government | Wikidata SPARQL | no |
| summary and thumbnail | Wikipedia REST | no |
| latest Sentinel-2 scene | Microsoft Planetary Computer STAC | no |

Every endpoint was called directly and its response inspected before being
written down here. Fan-out runs through a four-worker thread pool — the API's
routes are sync — with a 4 s timeout per upstream, so the whole call lands in
about 5 s worst case.

Displaying this data carries attribution obligations, which is why the panel
has a licence line: Copernicus Sentinel-2 is CC-BY 4.0 (EU / ESA), the summary
is CC-BY-SA, Wikidata is CC0, and the boundary file is public domain.

`NOTICE.md` is the repository's register of what this software fetches and what
it bundles, and it is not optional to keep current. The four services join the
feeds table pointing at `app/enrichment/place_screen.py`, and the 50 m boundary file
joins the bundled-data table beside the 110 m one.

### Partial failure is the normal case

Four third-party services will not all answer every time. A page that returns
500 because one of them hiccupped is worse than a page missing one block, so
**any source may fail and the rest still returns**. The response names the
blocks that did not answer:

```
{
  "point": { "lat": 57.14, "lon": -2.09 },
  "country": { "iso2": "GB", "name": "United Kingdom",
               "border_distance_km": 142.6, "near_border": false },
  "profile": { "capital": "...", "population": 0, "area_km2": 0,
               "languages": [], "currencies": [], "region": "...",
               "flag_png": "..." },
  "government": { "type": "...", "head_of_state": "...",
                  "head_of_government": "...", "as_of": "..." },
  "summary": { "title": "...", "extract": "...", "url": "...",
               "thumbnail": "..." },
  "imagery": { "url": "...", "full_url": "...", "captured_at": "...",
               "cloud_cover_pct": 28.4, "item_id": "..." },
  "degraded": ["government"]
}
```

Any block may be `null`; every null block is named in `degraded`, and that list
is what the panel's "unavailable" lines are driven by.

### The photograph

A STAC search over `sentinel-2-l2a`, intersecting the clicked point,
`eo:cloud_cover < 40`, newest first. The item's crop endpoint gives the
picture:

```
/api/data/v1/item/bbox/{minx},{miny},{maxx},{maxy}/512x512.png
    ?collection=sentinel-2-l2a&item={id}&assets=visual
    &asset_bidx=visual|1,2,3&nodata=0
```

The bbox is a small box around the click, not the scene's own footprint. A
Sentinel-2 tile is roughly 110 km across, so the whole-tile preview would show
a region when the reader asked about a point. Verified against a live call: the
cropped image resolves streets and a harbour.

Cloud cover is printed as a number. Sentinel-2's visual band is often half
white, and a white square with no explanation reads as a broken image rather
than as weather.

### Caching

In process, with TTLs — no table, no migration, nothing that grows against the
storage cap.

- Text blocks, keyed by ISO: 7 days. A capital city does not move.
- Photograph, keyed by lat/lon rounded to 0.05°: 12 hours. Sentinel-2 revisits
  every ~5 days, so a shorter TTL only buys repeated identical searches.

### Boundary accuracy

`app/enrichment/country.py` resolves points against Natural Earth 110 m, and
says in its own docstring that a point within ~10 km of a border may attribute
to the wrong side. Acceptable for month-scale country aggregates; not
acceptable for a page whose first line names the country.

A 50 m Admin-0 file ships beside the existing one, with its own lazily built
STRtree in a new function. Ingest keeps the 110 m path and pays neither the
memory nor the load time; nothing existing changes behaviour.

The response also carries the distance from the click to the country's border.
Under 5 km the identity block shows a "near border" note. Shapely gives this
for the cost of one distance call, and it stops the page stating a country with
more confidence than a polygon can support.

## Panel

`PlacePanel`, new, in `components/panels/`. It reads the store, calls the hook,
renders the blocks in the order drawn above, and mounts the existing
`CountrySidePanel` unchanged below the divider when there is an ISO.

Plumbing follows the existing shape: a fetch function in `lib/apiClient.ts`, a
react-query hook in `lib/queries.ts` beside `useCountryEvents`. Loading uses the
same skeleton treatment already in `CountrySidePanel`.

## Tests

Server, pytest with a stubbed `httpx.Client`:

- every source answers → every block populated, `degraded` empty
- one source raises → remaining blocks present, that block null and named
- all sources fail → 200 with a country and four named degradations, not a 500
- point over ocean → country null, photograph still attempted
- point near a border → `near_border` true, distance under threshold
- second identical call inside the TTL → no second upstream call
- 50 m lookup returns the correct side for a known cross-border pair

Frontend, vitest:

- `deckPageKeys` places `place` after `selection` in every flag combination
- the request URL is built from the clicked coordinates

The repository has no browser automation and no DOM test infrastructure, so the
panel's appearance ships unverified by machine and needs a human to look at it.
Stated rather than papered over.

## Out of scope

- Any second right-click gesture, menu or submenu. One gesture, one page.
- Historical imagery, band switching, a date picker.
- Storing any of this in the database.
- Touch equivalents for right-click.
