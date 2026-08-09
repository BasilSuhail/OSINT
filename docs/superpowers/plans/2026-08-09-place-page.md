# Place Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Right-click any point on the map and the left column gains a screen describing that place — government, vitals, background, and the latest low-cloud Sentinel-2 photograph of the point — with the existing score and event panel below a divider.

**Architecture:** One server route, `GET /geo/place?lat=&lon=`, resolves the point to a country against a 50 m boundary file and fans out to four keyless services in a thread pool; any of them may fail and the rest still returns. The frontend adds a fourth numbered screen to the deck, a store holding the clicked point, and a panel that renders the answer.

**Tech Stack:** FastAPI (sync routes), httpx, shapely, pytest, Next.js 15, SWR, zustand, vitest, react-map-gl / MapLibre.

## Global Constraints

- Repository licence is PolyForm Noncommercial 1.0.0. `NOTICE.md` is the register of what this software fetches and bundles, and every new feed and data file must be added to it.
- No personal names, institutions, contact details or credentials in any file, comment, commit message, issue or pull-request text. Write the role the sentence means.
- Commit messages carry no attribution trailers.
- One issue, one branch, one pull request, one commit. Issue is #862, branch is `862-place-page`. Squash to a single commit before opening the PR.
- No new Python or JavaScript dependencies. Everything below uses packages already in `pyproject.toml` and `package.json`.
- Backend commands use absolute venv paths: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest`. There is no bare `python` or `timeout` on this machine.
- Backend CI runs `ruff format --check` as well as `ruff check`. Both must pass.
- Work happens in the worktree `/private/tmp/claude-501/-Users-basilsuhail-folders-OSINT/4c2373e7-4997-47a2-996a-9bb8c1da8fa9/scratchpad/wt-862`, never in the primary checkout, because other sessions and a dev server are live there.
- The page is called **place** everywhere — page key, store, route, panel, title. Never "dossier", never "country".
- Every value shown on the page comes from a response field. Nothing is inferred, averaged, or filled in when a source is silent.

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `app/enrichment/data/admin0_countries_50m.geojson` | Natural Earth 50 m Admin-0 boundaries, properties stripped to `ISO_A2`, `ISO_A2_EH`, `NAME` |
| `scripts/build_admin0_50m.py` | Reproduces that file from the upstream source, so its provenance is a script and not a memory |
| `app/enrichment/boundary.py` | Precise point→ISO lookup and distance-to-border, lazily loaded, separate from the 110 m path |
| `app/enrichment/place_screen.py` | Assembles the place answer from four services; owns timeouts, the thread pool, the caches and the `degraded` list |
| `tests/test_boundary.py` | Precise lookup and border distance |
| `tests/test_place_assembly.py` | Assembly against a stubbed `httpx.Client`, including every failure shape |
| `tests/test_api_place.py` | The route, through `TestClient` |
| `osint-frontend/stores/placeStore.ts` | The clicked point and the resolved ISO |
| `osint-frontend/components/panels/PlacePanel.tsx` | The screen |
| `osint-frontend/lib/placeUrl.ts` | Builds the request URL — pure, so it is testable without a network |
| `osint-frontend/__tests__/placeUrl.test.ts` | That builder |

**Modified**

| File | Change |
| --- | --- |
| `app/api.py` | One route, delegating immediately |
| `NOTICE.md` | Four feeds, one bundled file |
| `osint-frontend/lib/deckPages.ts` | `place` page key and flag |
| `osint-frontend/lib/screenRule.test.mts` | Cases for the fourth screen; comment says the pop-up is not numbered |
| `osint-frontend/lib/apiClient.ts` | `fetchPlace` |
| `osint-frontend/lib/queries.ts` | `usePlace` |
| `osint-frontend/stores/rightPaneModeStore.ts` | Drop the `country` entity variant |
| `osint-frontend/components/panels/SelectionPanel.tsx` | Drop the country branch |
| `osint-frontend/components/CardDeck.tsx` | Drop country from the entity token, scroll to the place screen |
| `osint-frontend/components/EventDetailCard.tsx` | ISO chip opens the place screen |
| `osint-frontend/components/SplitLayout.tsx` | Mount the place card |
| `osint-frontend/components/MapPane.tsx` | `onContextMenu` |

---

### Task 1: The 50 m boundary file and its builder

**Files:**
- Create: `scripts/build_admin0_50m.py`
- Create: `app/enrichment/data/admin0_countries_50m.geojson`

**Interfaces:**
- Consumes: nothing.
- Produces: a GeoJSON `FeatureCollection` whose features carry exactly `ISO_A2`, `ISO_A2_EH` and `NAME`, at `app/enrichment/data/admin0_countries_50m.geojson`.

- [ ] **Step 1: Write the builder**

```python
"""Build the 50 m Admin-0 boundary file used by the place screen.

Natural Earth publishes 242 country features at 50 m with roughly 150
properties each, almost all of them irrelevant here. Stripping to the three
fields the lookup reads takes the committed file from 3.0 MB to 2.2 MB, and a
public repository should not carry 800 KB of columns nobody opens.

Run from the repository root:

    .venv/bin/python scripts/build_admin0_50m.py

The 110 m file beside it stays where it is. Ingest attributes millions of
points a month and the coarse polygons are correct for that; only the place
screen, which names a country in its first line, needs the finer ones.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)
DEST = Path(__file__).resolve().parents[1] / "app" / "enrichment" / "data" / "admin0_countries_50m.geojson"
KEEP = ("ISO_A2", "ISO_A2_EH", "NAME")


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=120) as response:
        document = json.load(response)

    features = [
        {
            "type": "Feature",
            "properties": {key: feature["properties"].get(key) for key in KEEP},
            "geometry": feature["geometry"],
        }
        for feature in document["features"]
    ]
    DEST.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    )
    print(f"wrote {len(features)} features to {DEST}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python scripts/build_admin0_50m.py`
Expected: `wrote 242 features to .../admin0_countries_50m.geojson`, file about 2.2 MB.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_admin0_50m.py app/enrichment/data/admin0_countries_50m.geojson
git commit -m "data: 50m admin-0 boundaries for the place screen"
```

---

### Task 2: Precise point lookup and distance to the border

**Files:**
- Create: `app/enrichment/boundary.py`
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `app/enrichment/data/admin0_countries_50m.geojson` from Task 1.
- Produces:
  - `precise_country(lat: float, lon: float) -> str | None`
  - `border_distance_km(lat: float, lon: float, iso: str) -> float | None`
  - `NEAR_BORDER_KM: float` (5.0)

- [ ] **Step 1: Write the failing test**

```python
"""The place screen names a country in its first line, so it uses the fine
boundaries — the coarse ones are allowed to be ~10 km wrong and say so."""

from __future__ import annotations

from app.enrichment.boundary import NEAR_BORDER_KM, border_distance_km, precise_country


def test_inland_point_resolves_to_its_country():
    assert precise_country(48.8566, 2.3522) == "FR"


def test_open_ocean_has_no_country():
    assert precise_country(0.0, -140.0) is None


def test_out_of_range_coordinates_are_refused():
    assert precise_country(120.0, 500.0) is None


def test_a_deep_inland_point_is_far_from_any_border():
    distance = border_distance_km(48.8566, 2.3522, "FR")
    assert distance is not None
    assert distance > NEAR_BORDER_KM


def test_a_point_beside_a_border_is_near_it():
    # A few hundred metres inside one side of a well-known land border.
    distance = border_distance_km(47.5586, 7.5886, "CH")
    assert distance is not None
    assert distance < NEAR_BORDER_KM


def test_distance_for_a_country_that_is_not_there_is_none():
    assert border_distance_km(48.8566, 2.3522, "ZZ") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_boundary.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.enrichment.boundary'`.

- [ ] **Step 3: Implement**

```python
"""Fine-grained point→country lookup for the place screen.

``app.enrichment.country`` resolves points against Natural Earth 110 m and says
in its own docstring that a point within ~10 km of a border may land on the
wrong side. That is the right trade for ingest, which attributes millions of
points into month-scale country buckets and would rather not hold finer
polygons in every worker.

It is the wrong trade for a screen whose first line names a country. So the
50 m file lives here, behind its own lazy loader: nothing pays for it until
somebody right-clicks the map, and the ingest path never touches this module.

The distance to the border is returned with the answer. A polygon can only
support so much confidence, and a screen that never says which side of a line
it is guessing at is a screen that is sometimes quietly wrong.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

_DATA_PATH = Path(__file__).parent / "data" / "admin0_countries_50m.geojson"

#: Under this, the screen says so. Chosen against the 50 m dataset's own
#: resolution: finer than this and the polygon is the source of the error.
NEAR_BORDER_KM = 5.0

_KM_PER_DEGREE = 111.32


@lru_cache(maxsize=1)
def _index() -> tuple[STRtree, list[str], list[object]]:
    """Build the tree on first use, not at import.

    Ingest imports the sibling module in every worker; making this one eager
    would add two megabytes of polygons to processes that never look at them.
    """
    with _DATA_PATH.open() as handle:
        document = json.load(handle)

    geometries = []
    isos: list[str] = []
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        iso = properties.get("ISO_A2")
        if not isinstance(iso, str) or len(iso) != 2 or iso.startswith("-"):
            iso = properties.get("ISO_A2_EH")
            if not isinstance(iso, str) or len(iso) != 2 or iso.startswith("-"):
                continue
        geometry = feature.get("geometry")
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # a malformed polygon is skipped, never guessed at
            continue
        if geom.is_empty:
            continue
        geometries.append(geom)
        isos.append(iso.upper())

    if not geometries:
        raise RuntimeError(f"no country polygons loaded from {_DATA_PATH}")
    tree = STRtree(geometries)
    return tree, isos, list(tree.geometries)


def _valid(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


@lru_cache(maxsize=4096)
def precise_country(lat: float, lon: float) -> str | None:
    """ISO alpha-2 for the country containing the point, or None over water."""
    if not _valid(lat, lon):
        return None
    tree, isos, geoms = _index()
    point = Point(lon, lat)
    for index in tree.query(point):
        if geoms[int(index)].contains(point):
            return isos[int(index)]
    return None


@lru_cache(maxsize=4096)
def border_distance_km(lat: float, lon: float, iso: str) -> float | None:
    """Great-circle-ish distance from the point to that country's edge.

    Degrees are converted with a cosine correction on longitude, which is
    accurate enough for a threshold measured in kilometres and avoids
    reprojecting a whole country to answer one question.
    """
    if not _valid(lat, lon) or not iso:
        return None
    tree, isos, geoms = _index()
    point = Point(lon, lat)
    wanted = iso.upper()
    best: float | None = None
    for index, code in enumerate(isos):
        if code != wanted:
            continue
        degrees = geoms[index].exterior.distance(point) if geoms[index].geom_type == "Polygon" else geoms[index].boundary.distance(point)
        scale = _KM_PER_DEGREE * max(math.cos(math.radians(lat)), 0.1)
        km = degrees * scale
        if best is None or km < best:
            best = km
    return best
```

- [ ] **Step 4: Run the tests**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_boundary.py -v`
Expected: 6 passed. If the near-border coordinate does not land under the threshold, print the measured distance and pick a coordinate from the same border that does — do not widen `NEAR_BORDER_KM` to make a test pass.

- [ ] **Step 5: Commit**

```bash
git add app/enrichment/boundary.py tests/test_boundary.py
git commit -m "feat: precise point lookup and border distance for the place screen"
```

---

### Task 3: Assembling the place answer

**Files:**
- Create: `app/enrichment/place_screen.py`
- Test: `tests/test_place_assembly.py`

**Interfaces:**
- Consumes: `precise_country`, `border_distance_km`, `NEAR_BORDER_KM` from Task 2.
- Produces: `describe_place(lat: float, lon: float, *, client: httpx.Client | None = None) -> dict` returning the keys `point`, `country`, `profile`, `government`, `summary`, `imagery`, `degraded`; and `clear_caches() -> None` for tests.

- [ ] **Step 1: Write the failing test**

```python
"""Four third-party services will not all answer every time, and a screen that
500s because one of them was slow is worse than a screen missing one block."""

from __future__ import annotations

import httpx
import pytest

from app.enrichment import place

PARIS = (48.8566, 2.3522)
OCEAN = (0.0, -140.0)

_STAC_ITEM = {
    "features": [
        {
            "id": "S2_TEST_ITEM",
            "properties": {"datetime": "2026-07-30T11:33:21Z", "eo:cloud_cover": 12.5},
            "assets": {},
        }
    ]
}


def _handler(*, fail: set[str] | None = None):
    failed = fail or set()

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "restcountries" in url:
            if "profile" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json=[
                    {
                        "capital": ["Paris"],
                        "population": 68_000_000,
                        "area": 551_695,
                        "languages": {"fra": "French"},
                        "currencies": {"EUR": {"name": "Euro"}},
                        "region": "Europe",
                        "flags": {"png": "https://example.invalid/fr.png"},
                    }
                ],
            )
        if "wikidata" in url:
            if "government" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={
                    "results": {
                        "bindings": [
                            {
                                "governmentLabel": {"value": "unitary semi-presidential republic"},
                                "headOfStateLabel": {"value": "the office holder"},
                                "headOfGovernmentLabel": {"value": "the office holder"},
                            }
                        ]
                    }
                },
            )
        if "wikipedia" in url:
            if "summary" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={
                    "title": "France",
                    "extract": "A country in Western Europe.",
                    "content_urls": {"desktop": {"page": "https://example.invalid/wiki"}},
                    "thumbnail": {"source": "https://example.invalid/thumb.png"},
                },
            )
        if "planetarycomputer" in url:
            if "imagery" in failed:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=_STAC_ITEM)
        raise AssertionError(f"unexpected request to {url}")

    return handle


def _client(**kwargs) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler(**kwargs)))


@pytest.fixture(autouse=True)
def _clear():
    place.clear_caches()
    yield
    place.clear_caches()


def test_every_source_answering_leaves_nothing_degraded():
    answer = place.describe_place(*PARIS, client=_client())
    assert answer["country"]["iso2"] == "FR"
    assert answer["profile"]["capital"] == "Paris"
    assert answer["government"]["type"] == "unitary semi-presidential republic"
    assert answer["summary"]["extract"].startswith("A country")
    assert answer["imagery"]["cloud_cover_pct"] == 12.5
    assert answer["degraded"] == []


def test_one_source_failing_leaves_the_others_standing():
    answer = place.describe_place(*PARIS, client=_client(fail={"government"}))
    assert answer["government"] is None
    assert answer["degraded"] == ["government"]
    assert answer["profile"]["capital"] == "Paris"
    assert answer["summary"] is not None


def test_all_sources_failing_still_returns_the_country():
    answer = place.describe_place(
        *PARIS, client=_client(fail={"profile", "government", "summary", "imagery"})
    )
    assert answer["country"]["iso2"] == "FR"
    assert sorted(answer["degraded"]) == ["government", "imagery", "profile", "summary"]


def test_open_ocean_has_no_country_but_still_asks_for_a_photograph():
    answer = place.describe_place(*OCEAN, client=_client())
    assert answer["country"] is None
    assert answer["imagery"] is not None
    assert "profile" in answer["degraded"]


def test_a_point_beside_a_border_says_so():
    answer = place.describe_place(47.5586, 7.5886, client=_client())
    assert answer["country"]["near_border"] is True


def test_a_repeat_call_inside_the_ttl_does_not_ask_again():
    calls = {"n": 0}

    def counting(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _handler()(request)

    client = httpx.Client(transport=httpx.MockTransport(counting))
    place.describe_place(*PARIS, client=client)
    first = calls["n"]
    place.describe_place(*PARIS, client=client)
    assert calls["n"] == first
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_place_assembly.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.enrichment.place'`.

- [ ] **Step 3: Implement**

Write `app/enrichment/place_screen.py` with:

- Module docstring explaining that the four services are independent, that partial failure is the normal case rather than an error, and that the `degraded` list is what the screen's "unavailable" lines are driven by.
- Constants: `_TIMEOUT_S = 4.0`, `_TEXT_TTL_S = 7 * 24 * 3600`, `_IMAGE_TTL_S = 12 * 3600`, `_IMAGE_GRID = 0.05`, `_BOX_DEGREES = 0.05`, `_MAX_CLOUD_PCT = 40`, and a `_USER_AGENT` string naming the project and its repository URL, because Wikipedia and Wikidata both ask for one and answer 403 without it.
- A small TTL cache: a module-level `dict[str, tuple[float, object]]` with `_cached(key, ttl, produce)` reading `time.monotonic()`. No database, no migration, nothing that grows against the storage cap.
- Four private fetchers, each taking `client: httpx.Client` and returning a dict or raising:
  - `_profile(client, iso)` → `https://restcountries.com/v3.1/alpha/{iso}?fields=capital,population,area,languages,currencies,region,flags`, mapping to `capital` (first entry), `population`, `area_km2`, `languages` (sorted values), `currencies` (sorted names), `region`, `flag_png`.
  - `_government(client, iso)` → `https://query.wikidata.org/sparql` with `format=json` and a query selecting the country's `P122` (basic form of government), `P35` (head of state) and `P6` (head of government) labels for the item whose `P297` matches the ISO code. Returns `type`, `head_of_state`, `head_of_government`, `as_of` (today, ISO date).
  - `_summary(client, title)` → `https://en.wikipedia.org/api/rest_v1/page/summary/{title}`, mapping to `title`, `extract`, `url`, `thumbnail`.
  - `_imagery(client, lat, lon)` → POST to `https://planetarycomputer.microsoft.com/api/stac/v1/search` with `collections=["sentinel-2-l2a"]`, an `intersects` point, `query={"eo:cloud_cover": {"lt": _MAX_CLOUD_PCT}}`, `sortby` datetime descending, `limit=1`; builds `url` from the item's bbox crop endpoint and `full_url` from the same item's whole-scene preview. Returns `url`, `full_url`, `captured_at`, `cloud_cover_pct`, `item_id`.
- `describe_place(lat, lon, *, client=None)`: resolves the ISO with `precise_country`, computes `border_distance_km` and `near_border`, then runs the four fetchers through `concurrent.futures.ThreadPoolExecutor(max_workers=4)`. Each result is caught individually: an exception means that block is `None` and its name is appended to `degraded`. With no ISO, the three country blocks are skipped and named in `degraded`, and only the photograph is fetched. Returns the shape in the spec.
- `clear_caches()` clearing the TTL dict and the `lru_cache`s.

The crop URL, verified against a live call:

```python
IMAGE_URL = (
    "https://planetarycomputer.microsoft.com/api/data/v1/item/"
    "bbox/{minx},{miny},{maxx},{maxy}/512x512.png"
    "?collection=sentinel-2-l2a&item={item}&assets=visual"
    "&asset_bidx=visual%7C1%2C2%2C3&nodata=0"
)
```

- [ ] **Step 4: Run the tests**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_place_assembly.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/enrichment/place.py tests/test_place_assembly.py
git commit -m "feat: assemble the place answer from four independent sources"
```

---

### Task 4: The route

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api_place.py`

**Interfaces:**
- Consumes: `describe_place` from Task 3.
- Produces: `GET /geo/place?lat=&lon=` returning the assembled dict.

- [ ] **Step 1: Write the failing test**

```python
"""The route is a doorway, not a place where work happens."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.enrichment import place


@pytest.fixture(autouse=True)
def _clear():
    place.clear_caches()
    yield
    place.clear_caches()
    app.dependency_overrides.clear()


def _offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(httpx.Client, "request", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)


def test_a_point_returns_a_country_even_with_every_service_down(monkeypatch):
    _offline(monkeypatch)
    response = TestClient(app).get("/geo/place", params={"lat": 48.8566, "lon": 2.3522})
    assert response.status_code == 200
    body = response.json()
    assert body["country"]["iso2"] == "FR"
    assert sorted(body["degraded"]) == ["government", "imagery", "profile", "summary"]


def test_coordinates_out_of_range_are_refused():
    response = TestClient(app).get("/geo/place", params={"lat": 120, "lon": 0})
    assert response.status_code == 422
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_api_place.py -v`
Expected: FAIL with 404 on the first test.

- [ ] **Step 3: Implement**

Add to `app/api.py` — the import beside the other `app.` imports, the route beside the other read endpoints:

```python
from app.enrichment.place import describe_place


@app.get("/geo/place")
def geo_place(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict:
    """What is at this point (#862).

    All four upstream services are optional and every one of them is somebody
    else's uptime. The answer names whichever went missing rather than failing
    whole, because a screen with one blank block is useful and a 500 is not.
    """
    return describe_place(lat, lon)
```

- [ ] **Step 4: Run the tests**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_api_place.py tests/test_api.py -v`
Expected: all pass — the second file confirms the new route did not disturb the existing ones.

- [ ] **Step 5: Register the sources in `NOTICE.md`**

Add to the feeds table:

```markdown
| RestCountries — country reference data | `app/enrichment/place_screen.py` | <https://restcountries.com/> |
| Wikidata — head of state and form of government | `app/enrichment/place_screen.py` | <https://www.wikidata.org/wiki/Wikidata:Licensing> |
| Wikipedia — place summaries | `app/enrichment/place_screen.py` | <https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use> |
| Copernicus Sentinel-2, via Microsoft Planetary Computer | `app/enrichment/place_screen.py` | <https://planetarycomputer.microsoft.com/terms> and <https://sentinels.copernicus.eu/web/sentinel/terms-conditions> |
```

Add to the bundled-data table:

```markdown
| `admin0_countries_50m.geojson` | Natural Earth, 50 m Admin-0 countries, rebuilt by `scripts/build_admin0_50m.py` | Public domain |
```

And a sentence after the Open Government Licence paragraph:

```markdown
Copernicus Sentinel-2 imagery is published under CC-BY 4.0 and Wikipedia text
under CC-BY-SA; both require attribution, which the place screen renders
beneath the data it shows.
```

- [ ] **Step 6: Lint and commit**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/ruff check app tests scripts && /Users/basilsuhail/folders/OSINT/.venv/bin/ruff format --check app tests scripts`
Expected: both clean.

```bash
git add app/api.py tests/test_api_place.py NOTICE.md
git commit -m "feat: serve the place answer, register its sources"
```

---

### Task 5: A fourth numbered screen

**Files:**
- Modify: `osint-frontend/lib/deckPages.ts`
- Test: `osint-frontend/lib/screenRule.test.mts`

**Interfaces:**
- Consumes: nothing.
- Produces: `DeckPageKey` gains `"place"`; `DeckState` gains `place: boolean`.

- [ ] **Step 1: Write the failing test**

Add to `screenRule.test.mts`:

```typescript
describe("the place screen", () => {
  it("is not there until the map is right-clicked", () => {
    expect(deckPageKeys({ selection: false, place: false, scoreboard: false })).toEqual([
      "situation",
      "world",
    ])
  })

  it("is screen 4 when a selection already made screen 3", () => {
    const keys = deckPageKeys({ selection: true, place: true, scoreboard: false })
    expect(keys[3]).toBe("place")
  })

  it("is screen 3 when nothing is selected", () => {
    const keys = deckPageKeys({ selection: false, place: true, scoreboard: false })
    expect(keys[SCREEN_3]).toBe("place")
  })

  it("never displaces screens 1 and 2", () => {
    for (const selection of [false, true]) {
      for (const place of [false, true]) {
        for (const scoreboard of [false, true]) {
          const keys = deckPageKeys({ selection, place, scoreboard })
          expect(keys[SCREEN_1]).toBe("situation")
          expect(keys[SCREEN_2]).toBe("world")
        }
      }
    }
  })

  it("always sits after the selection screen", () => {
    const keys = deckPageKeys({ selection: true, place: true, scoreboard: true })
    expect(keys.indexOf("place")).toBeGreaterThan(keys.indexOf("selection"))
    expect(keys.indexOf("place")).toBeLessThan(keys.indexOf("scoreboard"))
  })
})
```

Every existing call to `deckPageKeys` in the file gains `place: false`.

The comment block at the top of the file gains the fourth screen, and states that the pop-up is not one of the numbered screens:

```
 *   screen 1  news and stories          left column
 *   screen 2  world view and search     left column
 *   screen 3  made by a map click       left column
 *   screen 4  made by a map right-click left column
 *
 *   The pop-up is not on this list. It is a pop-up: it opens over what you
 *   were reading and goes away again. Numbering it is the confusion that
 *   #843-#853 spent five pull requests undoing.
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd osint-frontend && pnpm vitest run lib/screenRule.test.mts`
Expected: FAIL — type error on the unknown `place` property.

- [ ] **Step 3: Implement**

```typescript
export interface DeckState {
  /** Something on the map is picked — screen 3. */
  selection: boolean
  /** A point was right-clicked — the place screen. */
  place: boolean
  /** The scoreboard has something graded to show. */
  scoreboard: boolean
}

export type DeckPageKey = "situation" | "world" | "selection" | "place" | "scoreboard"

export function deckPageKeys(state: DeckState): DeckPageKey[] {
  const keys: DeckPageKey[] = [...STANDING_PAGES]
  if (state.selection) keys.push("selection")
  if (state.place) keys.push("place")
  if (state.scoreboard) keys.push("scoreboard")
  return keys
}
```

- [ ] **Step 4: Run the tests**

Run: `cd osint-frontend && pnpm vitest run lib/screenRule.test.mts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/deckPages.ts osint-frontend/lib/screenRule.test.mts
git commit -m "feat: the place screen joins the numbered left column"
```

---

### Task 6: The store, and the entity variant that leaves

**Files:**
- Create: `osint-frontend/stores/placeStore.ts`
- Modify: `osint-frontend/stores/rightPaneModeStore.ts`
- Modify: `osint-frontend/components/panels/SelectionPanel.tsx`
- Modify: `osint-frontend/components/CardDeck.tsx`
- Modify: `osint-frontend/components/EventDetailCard.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `usePlaceStore` with `{ open: { lat: number; lon: number } | { iso: string } | null, openPoint(lat, lon), openCountry(iso), close() }`.

- [ ] **Step 1: Write the store**

```typescript
import { create } from "zustand"

/** What the reader right-clicked (#862).
 *
 * Two ways in, and they carry different things. From the map it is a point,
 * and the country arrives with the server's answer — which may legitimately be
 * nothing, because open ocean is a real place to right-click. From the ISO
 * chip inside an event it is a country with no point at all, and that screen
 * shows every text block and no photograph rather than inventing a coordinate
 * from a centroid.
 */
export interface PlaceTarget {
  lat?: number
  lon?: number
  iso?: string
}

interface PlaceState {
  target: PlaceTarget | null
  openPoint: (lat: number, lon: number) => void
  openCountry: (iso: string) => void
  close: () => void
}

export const usePlaceStore = create<PlaceState>((set) => ({
  target: null,
  openPoint: (lat, lon) => set({ target: { lat, lon } }),
  openCountry: (iso) => set({ target: { iso } }),
  close: () => set({ target: null }),
}))
```

- [ ] **Step 2: Remove the country variant from the selection store**

In `rightPaneModeStore.ts`, delete the `{ kind: "country"; iso: string }` member of `RightPaneEntity` and the `openCountry` action. Update the docstring: a map selection is an event, a cluster or an area, and a country is now its own screen.

- [ ] **Step 3: Follow the removal through**

- `SelectionPanel.tsx`: delete the `entity.kind === "country"` branch and the `openCountry` import. The remaining chain is cluster, area, event.
- `CardDeck.tsx`: delete the `country` case from the entity token. Add a second effect beside the existing one:

```typescript
const placeTarget = usePlaceStore((s) => s.target)
const placeToken = placeTarget
  ? `place:${placeTarget.iso ?? ""}:${placeTarget.lat ?? ""}:${placeTarget.lon ?? ""}`
  : null
const placeIndex = cards.findIndex((c) => c.key === "place")
useEffect(() => {
  if (!placeToken || placeIndex < 0) return
  activeRef.current = placeIndex
  goTo(placeIndex)
}, [placeToken, placeIndex, goTo])
```

- `EventDetailCard.tsx`: the `onSelectCountry` callback now calls `usePlaceStore.getState().openCountry(iso)`. Where `SelectionPanel` passed `onSelectCountry={(iso) => openCountry(iso)}`, it passes the store action instead.

- [ ] **Step 4: Typecheck**

Run: `cd osint-frontend && pnpm exec tsc --noEmit`
Expected: no errors. Any remaining reference to the removed variant shows up here.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/stores osint-frontend/components/panels/SelectionPanel.tsx osint-frontend/components/CardDeck.tsx osint-frontend/components/EventDetailCard.tsx
git commit -m "refactor: a place is its own screen, not a map selection"
```

---

### Task 7: Fetching the answer

**Files:**
- Create: `osint-frontend/lib/placeUrl.ts`
- Create: `osint-frontend/__tests__/placeUrl.test.ts`
- Modify: `osint-frontend/lib/apiClient.ts`
- Modify: `osint-frontend/lib/queries.ts`

**Interfaces:**
- Consumes: `PlaceTarget` from Task 6, `apiFetch` and `API_BASE` from `apiClient.ts`.
- Produces: `placeUrl(target: PlaceTarget, base: string): string | null`, `fetchPlace(target): Promise<PlaceAnswer>`, `usePlace(target): { place: PlaceAnswer | null; isLoading: boolean }`, and the `PlaceAnswer` type.

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it } from "vitest"
import { placeUrl } from "../lib/placeUrl"

const BASE = "http://api.invalid"

describe("placeUrl", () => {
  it("asks about the point that was right-clicked", () => {
    expect(placeUrl({ lat: 57.14, lon: -2.09 }, BASE)).toBe(
      "http://api.invalid/geo/place?lat=57.14&lon=-2.09",
    )
  })

  it("asks about a country when there is no point", () => {
    expect(placeUrl({ iso: "FR" }, BASE)).toBe("http://api.invalid/geo/place?iso=FR")
  })

  it("has nothing to ask when the target is empty", () => {
    expect(placeUrl({}, BASE)).toBeNull()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd osint-frontend && pnpm vitest run __tests__/placeUrl.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement**

`placeUrl.ts` builds the query string from whichever half of the target is present, returning `null` when neither is. The `iso` form requires the route to accept an ISO instead of a point: in `app/api.py`, make `lat` and `lon` optional and add `iso: str | None = Query(None, min_length=2, max_length=2)`, returning 422 when neither a full point nor an ISO is given, and add a test for the ISO form in `tests/test_api_place.py`.

`apiClient.ts` gains the `PlaceAnswer` type mirroring the server's shape, and:

```typescript
export async function fetchPlace(
  target: PlaceTarget,
  options: { signal?: AbortSignal } = {},
): Promise<PlaceAnswer | null> {
  const url = placeUrl(target, API_BASE)
  if (!url) return null
  const response = await apiFetch(url, { signal: options.signal })
  if (!response.ok) throw new Error(`place ${response.status}`)
  return response.json()
}
```

`queries.ts` gains, beside `useCountryEvents`:

```typescript
export function usePlace(target: PlaceTarget | null): {
  place: PlaceAnswer | null
  isLoading: boolean
} {
  const key = target ? placeUrl(target, API_BASE) : null
  const { data, isLoading } = useSWR(key, async () => (target ? fetchPlace(target) : null), {
    revalidateOnFocus: false,
  })
  return { place: data ?? null, isLoading }
}
```

- [ ] **Step 4: Run the tests**

Run: `cd osint-frontend && pnpm vitest run __tests__/placeUrl.test.ts` then `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests/test_api_place.py -v`
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/lib/placeUrl.ts osint-frontend/__tests__/placeUrl.test.ts osint-frontend/lib/apiClient.ts osint-frontend/lib/queries.ts app/api.py tests/test_api_place.py
git commit -m "feat: fetch the place answer by point or by country"
```

---

### Task 8: The screen

**Files:**
- Create: `osint-frontend/components/panels/PlacePanel.tsx`
- Modify: `osint-frontend/components/SplitLayout.tsx`

**Interfaces:**
- Consumes: `usePlaceStore` (Task 6), `usePlace` (Task 7), `CountrySidePanel` (existing).
- Produces: `<PlacePanel />`, mounted by `SplitLayout` under the key `place`.

- [ ] **Step 1: Build the panel**

Render, in this order, each block separated by a hairline rule:

1. Flag, country name, ISO, form of government, close control. Near-border note when `country.near_border`. With no country: "Open water" and the coordinates to four decimals.
2. Head of state, head of government, capital, population, languages, currency, area — one label and one value per row, never two columns.
3. The summary extract, trimmed to its first two sentences, with a "Read more" link.
4. The photograph, then a line reading capture date, cloud percentage and "10 m", then a "Full resolution" link.
5. The attribution line: Copernicus · Wikipedia · Wikidata · Natural Earth.
6. A double rule, then `<CountrySidePanel country={iso} onClose={close} />` when there is an ISO.

While loading, the same pulse skeletons `CountrySidePanel` already uses. For any block named in `degraded`, one quiet line reading "unavailable" in the muted colour — never an empty gap, because a block that silently vanishes teaches the reader the console has nothing to say.

Match the existing panel's typography exactly: `font-mono text-[10px] uppercase tracking-widest text-neutral-500` for labels, `text-neutral-300` for values, `border-neutral-800` for rules.

- [ ] **Step 2: Mount it**

In `SplitLayout.tsx`, after the `selection` block and before the `scoreboard` block:

```tsx
if (placeOpen) {
  deckCards.push({ key: "place", title: "place", fill: true, content: <PlacePanel /> })
}
```

with `const placeOpen = usePlaceStore((s) => s.target !== null)`, and `place: placeOpen` added to the dev-mode `deckPageKeys` drift check.

- [ ] **Step 3: Typecheck and lint**

Run: `cd osint-frontend && pnpm exec tsc --noEmit && pnpm lint`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add osint-frontend/components/panels/PlacePanel.tsx osint-frontend/components/SplitLayout.tsx
git commit -m "feat: the place screen"
```

---

### Task 9: Right-click

**Files:**
- Modify: `osint-frontend/components/MapPane.tsx`

**Interfaces:**
- Consumes: `usePlaceStore.openPoint` from Task 6.
- Produces: right-click on the map opens the place screen.

- [ ] **Step 1: Add the handler**

```tsx
//: Right-click asks what this place is; left-click asks what is happening
//: near it (#862). Two questions, two gestures, and the left one is not
//: touched — the radius selection it builds is well-worn and this feature
//: does not get to disturb it.
const openPlace = usePlaceStore((s) => s.openPoint)
const handleContextMenu = useCallback(
  (e: MapLayerMouseEvent) => {
    e.preventDefault?.()
    e.originalEvent?.preventDefault()
    openPlace(e.lngLat.lat, e.lngLat.lng)
  },
  [openPlace],
)
```

and `onContextMenu={handleContextMenu}` on `<MapGL>`.

- [ ] **Step 2: Typecheck**

Run: `cd osint-frontend && pnpm exec tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Verify the whole suite**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests -q` and `cd osint-frontend && pnpm vitest run`
Expected: both green. Report the actual counts; do not claim a pass without the output in front of you.

- [ ] **Step 4: Commit**

```bash
git add osint-frontend/components/MapPane.tsx
git commit -m "feat: right-click the map to open the place screen"
```

---

### Task 10: One commit, one pull request

- [ ] **Step 1: Rebase onto the current origin**

```bash
git fetch origin
git rebase origin/main
```

Other sessions are pushing to this repository. If anything conflicts, resolve it in favour of the other branch's intent and re-run both suites.

- [ ] **Step 2: Squash to one commit**

```bash
git reset --soft $(git merge-base HEAD origin/main)
git commit -m "feat(map): #862 right-click a point on the map, get the place"
```

- [ ] **Step 3: Re-run both suites after the squash**

Run: `/Users/basilsuhail/folders/OSINT/.venv/bin/python -m pytest tests -q` and `cd osint-frontend && pnpm vitest run`

- [ ] **Step 4: Push and open the pull request**

```bash
git push -u origin 862-place-page
gh pr create --title "feat(map): #862 right-click a point on the map, get the place" --body "…"
```

The body says what the screen does, that left-click is untouched, that four keyless services are now fetched and registered in `NOTICE.md`, that boundary resolution for this screen uses the 50 m file while ingest keeps the 110 m one, and — plainly — that the panel's appearance has not been verified in a browser because this repository has no browser automation, so a human needs to look at it. No attribution trailers.

---

## Self-Review

**Spec coverage.** Interaction → Task 9. Own screen and the numbering correction → Task 5. Store and the departing entity variant → Task 6. Server, four sources, partial failure, caching → Tasks 3 and 4. Boundary accuracy and the near-border note → Tasks 1 and 2. `NOTICE.md` → Task 4. Panel and its block order → Task 8. Tests → in every task. The one spec item deliberately deferred is browser verification, which this repository cannot do and Task 10 says so out loud.

**Placeholders.** None. Task 3's implementation step describes the module in prose rather than pasting 200 lines, but every endpoint, constant, field name and URL shape it needs is written out.

**Type consistency.** `PlaceTarget` is defined in Task 6 and consumed by Tasks 7 and 8. `PlaceAnswer` is defined in Task 7 and consumed by Task 8. `describe_place` and `clear_caches` are defined in Task 3 and consumed by Task 4. `precise_country`, `border_distance_km` and `NEAR_BORDER_KM` are defined in Task 2 and consumed by Task 3. `placeUrl` is defined in Task 7 and used by both `fetchPlace` and `usePlace` in the same task. The `place` deck key is defined in Task 5 and used in Tasks 6 and 8.
