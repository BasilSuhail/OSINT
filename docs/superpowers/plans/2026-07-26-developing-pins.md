# Pinned Developing Stories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin 2–3 multi-day international stories that are still gathering coverage above the Situation card's activity list, selected by a deterministic rule.

**Architecture:** A pure selector module aggregates each candidate story over its members and applies four gates (severity floor, country spread, velocity, age). A new read-only endpoint exposes the survivors with a `pin_reasons` block. The Situation panel renders them as a `DEVELOPING` block under the brain headline and filters them out of the list below.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (`select`, `Mapped`), pytest against in-memory SQLite; Next.js 16 + React 19, SWR, Tailwind, vitest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-26-developing-pins-design.md`. Every threshold below is copied from it verbatim.
- Thresholds: `max(events.severity) >= 0.6`, `count(distinct events.country) >= 3`, `>= 1` member with `added_at` inside 12 h, `now() - first_seen >= 24 h`, candidate `last_seen` inside 6 h.
- Ranking: velocity desc, then country spread desc, then `outlet_count` desc. Default limit 3.
- Corroboration is **shown, never gated** — no corroboration term appears in any gate.
- Empty result is a normal empty list / a `null` render. Thresholds are never relaxed to fill the slot.
- Queries must run on SQLite (the unit suite is hermetic per `tests/conftest.py`) — no Postgres-only SQL, no `interval` literals. Use `func.max`, `func.count(distinct(...))` and Python `timedelta` cutoffs.
- Every public function takes an injectable `now: datetime | None = None` so tests are deterministic; production passes nothing and gets `datetime.now(UTC)`.
- Backend gates before commit: `ruff check .` **and** `ruff format --check .` **and** `pytest`.
- No new dependencies, backend or frontend.

---

### Task 1: Selector module

**Files:**
- Create: `app/stories/developing.py`
- Test: `tests/test_stories_developing.py`

**Interfaces:**
- Consumes: `app.db_models.StoryRow`, `StoryMemberRow`, `EventRow` (existing).
- Produces:
  ```python
  METHOD_VERSION: str = "developing-v1.0"
  CANDIDATE_LAST_SEEN_HOURS: int = 6
  MIN_AGE_HOURS: int = 24
  MIN_MAX_SEVERITY: float = 0.6
  MIN_COUNTRIES: int = 3
  VELOCITY_WINDOW_HOURS: int = 12
  MIN_NEW_MEMBERS: int = 1
  DEFAULT_LIMIT: int = 3

  def select_developing(
      session: Session, *, limit: int = DEFAULT_LIMIT, now: datetime | None = None
  ) -> list[dict[str, Any]]
  ```
  Each returned dict is exactly:
  ```python
  {"story_id": int, "pin_reasons": {
      "max_severity": float, "countries": int,
      "new_members_12h": int, "age_hours": int}}
  ```
  Ordered best-first. `age_hours` is floored to a whole hour.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stories_developing.py`:

```python
"""Selection rule for the pinned developing stories (#449)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryMemberRow, StoryRow
from app.stories.developing import select_developing

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _story(
    session: Session,
    *,
    title: str,
    age_hours: int = 48,
    last_seen_hours: int = 1,
    outlet_count: int = 5,
) -> int:
    story = StoryRow(
        title=title,
        first_seen=NOW - timedelta(hours=age_hours),
        last_seen=NOW - timedelta(hours=last_seen_hours),
        member_count=outlet_count,
        outlet_count=outlet_count,
        owner_count=outlet_count,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    return story.id


def _member(
    session: Session,
    story_id: int,
    *,
    severity: float,
    country: str,
    added_hours: int = 2,
) -> None:
    event = EventRow(
        source="rss",
        source_event_id=f"{story_id}-{country}-{added_hours}-{severity}",
        occurred_at=NOW - timedelta(hours=added_hours),
        category="news",
        severity=severity,
        country=country,
        payload={"title": f"member {country}"},
    )
    session.add(event)
    session.flush()
    session.add(
        StoryMemberRow(
            event_id=event.id,
            story_id=story_id,
            similarity=0.5,
            added_at=NOW - timedelta(hours=added_hours),
        )
    )
    session.flush()


def _qualifying(session: Session, title: str = "widening exchange", **kw) -> int:
    """A story that clears every gate: 0.6 severity, 3 countries, fresh members."""
    sid = _story(session, title=title, **kw)
    for country in ("IR", "UA", "RO"):
        _member(session, sid, severity=0.6, country=country)
    return sid


def test_qualifying_story_is_pinned_with_reasons(db_session: Session) -> None:
    sid = _qualifying(db_session)
    rows = select_developing(db_session, now=NOW)
    assert [r["story_id"] for r in rows] == [sid]
    assert rows[0]["pin_reasons"] == {
        "max_severity": 0.6,
        "countries": 3,
        "new_members_12h": 3,
        "age_hours": 48,
    }


def test_low_severity_rejected(db_session: Session) -> None:
    sid = _story(db_session, title="tour de france stage win")
    for country in ("FR", "BE", "ES"):
        _member(db_session, sid, severity=0.3, country=country)
    assert select_developing(db_session, now=NOW) == []


def test_two_countries_rejected(db_session: Session) -> None:
    sid = _story(db_session, title="domestic protest")
    for country in ("IN", "IN", "LK"):
        _member(db_session, sid, severity=0.8, country=country)
    assert select_developing(db_session, now=NOW) == []


def test_no_recent_member_rejected(db_session: Session) -> None:
    sid = _story(db_session, title="story that stopped gathering")
    for country in ("IR", "UA", "RO"):
        _member(db_session, sid, severity=0.7, country=country, added_hours=30)
    assert select_developing(db_session, now=NOW) == []


def test_too_young_rejected(db_session: Session) -> None:
    _qualifying(db_session, title="flash from this morning", age_hours=5)
    assert select_developing(db_session, now=NOW) == []


def test_stale_story_rejected(db_session: Session) -> None:
    """last_seen outside the candidate window — nothing has arrived in days."""
    sid = _story(db_session, title="cold story", last_seen_hours=40)
    for country in ("IR", "UA", "RO"):
        _member(db_session, sid, severity=0.7, country=country, added_hours=40)
    assert select_developing(db_session, now=NOW) == []


def test_ranks_by_velocity_then_spread_then_outlets(db_session: Session) -> None:
    slow = _story(db_session, title="slow", outlet_count=9)
    for country in ("IR", "UA", "RO"):
        _member(db_session, slow, severity=0.6, country=country)

    fast = _story(db_session, title="fast", outlet_count=4)
    for i, country in enumerate(("IR", "UA", "RO", "PL", "DE")):
        _member(db_session, fast, severity=0.6, country=country, added_hours=i + 1)

    rows = select_developing(db_session, now=NOW)
    assert [r["story_id"] for r in rows] == [fast, slow]


def test_limit_respected(db_session: Session) -> None:
    for i in range(4):
        _qualifying(db_session, title=f"story {i}")
    assert len(select_developing(db_session, limit=3, now=NOW)) == 3


def test_missing_severity_does_not_qualify(db_session: Session) -> None:
    """An ungraded story has no max severity — it must not slip through as 0."""
    sid = _story(db_session, title="ungraded")
    for country in ("IR", "UA", "RO"):
        _member(db_session, sid, severity=None, country=country)
    assert select_developing(db_session, now=NOW) == []


def test_null_country_not_counted_as_spread(db_session: Session) -> None:
    sid = _story(db_session, title="two known countries plus unknowns")
    _member(db_session, sid, severity=0.7, country="IR")
    _member(db_session, sid, severity=0.7, country="UA")
    _member(db_session, sid, severity=0.7, country=None)
    assert select_developing(db_session, now=NOW) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_stories_developing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.stories.developing'`

- [ ] **Step 3: Write the implementation**

Create `app/stories/developing.py`:

```python
"""Which stories earn the Situation card's pinned slot (#449).

Declared mechanics under METHOD_VERSION, no tuning at read time. A story is
"developing" when four things hold at once:

    max(member severity) >= 0.6     it is about harm, not a heritage listing
    distinct member countries >= 3  the world is telling it, not one capital
    >= 1 member added in 12 h       coverage is still arriving
    first_seen at least 24 h ago    it has lasted more than one news cycle

Ranked velocity first, so the pin tracks what is *moving*, not what is
merely large. Corroboration is deliberately absent from every gate: a
widely-told story with few independent owners is exactly what the card must
keep visible (#363/#365, #641), so it is displayed alongside the pin rather
than used to suppress it.

Calibrated 2026-07-26 against live data while the #597 news severity regrade
stood at ~23.3k of ~25.9k rows. On that snapshot the gates returned four
candidates (West Bank arrests, Romania/drone, Typhoon Noul, Iran/Ukraine)
and rejected the naive outlet-count rule's false pins (Mount Olympus Unesco
listing, a Tour de France stage report, an Indian cabinet appointment).
Re-check these constants at full severity coverage: the known false negative
is the France wildfires, held out at max severity 0.5 because only 15 of its
22 members carried the new grade.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryMemberRow, StoryRow

METHOD_VERSION: str = "developing-v1.0"

#: A candidate must have been touched this recently to count as live at all.
CANDIDATE_LAST_SEEN_HOURS: int = 6
#: "Multi-day" — younger than this is a flash, not a developing situation.
MIN_AGE_HOURS: int = 24
#: Harm floor on the news severity scale (#591).
MIN_MAX_SEVERITY: float = 0.6
#: Distinct member countries; below this it is a domestic story.
MIN_COUNTRIES: int = 3
#: Window over which "still gathering coverage" is measured.
VELOCITY_WINDOW_HOURS: int = 12
MIN_NEW_MEMBERS: int = 1
DEFAULT_LIMIT: int = 3


def select_developing(
    session: Session, *, limit: int = DEFAULT_LIMIT, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Story ids to pin, best-first, each with the evidence for its pin.

    Returns at most `limit` rows. An empty list is a normal answer: nothing
    developing means nothing pinned, and the thresholds are never relaxed to
    fill the slot.
    """
    now = now or datetime.now(UTC)
    fresh_cutoff = now - timedelta(hours=CANDIDATE_LAST_SEEN_HOURS)
    age_cutoff = now - timedelta(hours=MIN_AGE_HOURS)
    velocity_cutoff = now - timedelta(hours=VELOCITY_WINDOW_HOURS)

    max_severity = func.max(EventRow.severity)
    countries = func.count(distinct(EventRow.country))
    new_members = func.sum(case((StoryMemberRow.added_at >= velocity_cutoff, 1), else_=0))

    stmt = (
        select(
            StoryRow.id,
            StoryRow.first_seen,
            max_severity.label("max_severity"),
            countries.label("countries"),
            new_members.label("new_members"),
        )
        .join(StoryMemberRow, StoryMemberRow.story_id == StoryRow.id)
        .join(EventRow, EventRow.id == StoryMemberRow.event_id)
        .where(StoryRow.last_seen >= fresh_cutoff, StoryRow.first_seen <= age_cutoff)
        .group_by(StoryRow.id, StoryRow.first_seen, StoryRow.outlet_count)
        .having(max_severity >= MIN_MAX_SEVERITY)
        .having(countries >= MIN_COUNTRIES)
        .having(new_members >= MIN_NEW_MEMBERS)
        .order_by(new_members.desc(), countries.desc(), StoryRow.outlet_count.desc())
        .limit(limit)
    )

    return [
        {
            "story_id": row.id,
            "pin_reasons": {
                "max_severity": row.max_severity,
                "countries": row.countries,
                "new_members_12h": int(row.new_members),
                "age_hours": int((now - row.first_seen).total_seconds() // 3600),
            },
        }
        for row in session.execute(stmt).all()
    ]
```

Note on `count(distinct EventRow.country)`: SQL `COUNT(DISTINCT col)` skips NULLs,
which is why `test_null_country_not_counted_as_spread` passes without extra code.
`MAX(severity)` over all-NULL severities returns NULL, and `NULL >= 0.6` is not true,
so `test_missing_severity_does_not_qualify` passes for the same reason.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_stories_developing.py -v`
Expected: 10 passed.

- [ ] **Step 5: Lint, format, commit**

```bash
ruff check app/stories/developing.py tests/test_stories_developing.py
ruff format app/stories/developing.py tests/test_stories_developing.py
pytest tests/test_stories_developing.py -q
git add app/stories/developing.py tests/test_stories_developing.py
git commit -m "feat(stories): #449 selector for pinned developing stories"
```

---

### Task 2: Endpoint

**Files:**
- Modify: `app/api.py` — extract the row payload from `stories_top` (currently `app/api.py:341-399`), then add the new route directly beneath it
- Test: `tests/test_api_developing.py`

**Interfaces:**
- Consumes: `select_developing`, `METHOD_VERSION`, `DEFAULT_LIMIT` from Task 1.
- Produces:
  ```python
  def _story_payload(
      story: StoryRow,
      corro: StoryCorroborationRow | None,
      checks: dict[str, str],
      gist: StoryGistRow | None,
  ) -> dict
  ```
  and the route `GET /stories/developing?limit=3` returning
  `list[_story_payload(...) | {"pin_reasons": {...}}]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_developing.py`:

```python
"""GET /stories/developing — the Situation card's pinned slot (#449)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import (
    Base,
    EventRow,
    StoryCorroborationRow,
    StoryMemberRow,
    StoryRow,
)


def _seed(session: Session, *, title: str, severity: float, countries: tuple[str, ...]) -> int:
    now = datetime.now(UTC)
    story = StoryRow(
        title=title,
        first_seen=now - timedelta(hours=48),
        last_seen=now - timedelta(hours=1),
        member_count=len(countries),
        outlet_count=len(countries),
        owner_count=len(countries),
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    for i, country in enumerate(countries):
        event = EventRow(
            source="rss",
            source_event_id=f"{title}-{i}",
            occurred_at=now - timedelta(hours=2),
            category="news",
            severity=severity,
            country=country,
            payload={"title": f"{title} {country}"},
        )
        session.add(event)
        session.flush()
        session.add(
            StoryMemberRow(
                event_id=event.id,
                story_id=story.id,
                similarity=0.5,
                added_at=now - timedelta(hours=2),
            )
        )
    session.flush()
    return story.id


def _client(seed) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        seed(s)
        s.commit()

    def override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_pinned_story_carries_reasons_and_corroboration() -> None:
    def seed(s: Session) -> None:
        sid = _seed(s, title="widening exchange", severity=0.6, countries=("IR", "UA", "RO"))
        s.add(
            StoryCorroborationRow(
                story_id=sid,
                score=0.62,
                components={"owners": 3},
                method_version="corroboration-v1.0",
            )
        )

    client = _client(seed)
    try:
        res = client.get("/stories/developing")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        row = body[0]
        assert row["title"] == "widening exchange"
        assert row["outlet_count"] == 3
        assert row["owner_count"] == 3
        assert row["corroboration"] == 0.62
        assert row["pin_reasons"]["countries"] == 3
        assert row["pin_reasons"]["max_severity"] == 0.6
        assert row["pin_reasons"]["new_members_12h"] == 3
        assert row["pin_reasons"]["age_hours"] == 48
    finally:
        app.dependency_overrides.clear()


def test_nothing_developing_returns_empty_list() -> None:
    def seed(s: Session) -> None:
        _seed(s, title="stage win", severity=0.3, countries=("FR", "BE", "ES"))

    client = _client(seed)
    try:
        res = client.get("/stories/developing")
        assert res.status_code == 200
        assert res.json() == []
    finally:
        app.dependency_overrides.clear()


def test_limit_is_capped() -> None:
    def seed(s: Session) -> None:
        for i in range(5):
            _seed(s, title=f"story {i}", severity=0.7, countries=("IR", "UA", "RO"))

    client = _client(seed)
    try:
        assert len(client.get("/stories/developing?limit=2").json()) == 2
        assert client.get("/stories/developing?limit=99").status_code == 422
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_api_developing.py -v`
Expected: FAIL — all three tests 404, because the route does not exist.

- [ ] **Step 3: Extract the shared row payload**

In `app/api.py`, add above `stories_top`:

```python
def _story_payload(
    story: StoryRow,
    corro: StoryCorroborationRow | None,
    checks: dict[str, str],
    gist: StoryGistRow | None,
) -> dict:
    """One story as the API renders it — shared by /stories/top and
    /stories/developing so a pinned row and a list row never drift apart."""
    return {
        "id": str(story.id),
        "title": story.title,
        "first_seen": story.first_seen.isoformat(),
        "last_seen": story.last_seen.isoformat(),
        "member_count": story.member_count,
        "outlet_count": story.outlet_count,
        "owner_count": story.owner_count,
        "corroboration": corro.score if corro else None,
        "corroboration_components": corro.components if corro else None,
        "sensor_checks": checks,
        "method_version": story.method_version,
        "gist": gist.gist if gist else None,
        "category": gist.category if gist else None,
        "escalating": gist.escalating if gist else None,
    }
```

Then replace the return statement of `stories_top` (the list comprehension at
`app/api.py:381-399`) with:

```python
    return [
        _story_payload(story, corro, checks.get(story.id, {}), gists.get(story.id))
        for story, corro in rows
    ]
```

- [ ] **Step 4: Verify the extraction changed no behaviour**

Run: `pytest tests/test_api.py tests/test_api_analytics.py tests/test_api_story_detail.py -q`
Expected: PASS, same counts as before the edit. A failure here means the payload
extraction is not faithful — fix it before adding the route.

- [ ] **Step 5: Add the route**

Immediately after `stories_top` in `app/api.py`:

```python
@app.get("/stories/developing")
def stories_developing(
    session: Session = Depends(get_session),
    limit: int = Query(default=developing.DEFAULT_LIMIT, ge=1, le=10),
) -> list[dict]:
    """The Situation card's pinned slot (#449) — multi-day international
    stories still gathering coverage, best-first.

    Same row shape as /stories/top plus `pin_reasons`, the evidence for the
    pin: the card justifies a pin rather than asserting it. Corroboration
    rides along and is never a gate — a widely-told story with few
    independent owners is precisely what must stay visible.
    """
    picks = developing.select_developing(session, limit=limit)
    if not picks:
        return []

    order = {p["story_id"]: i for i, p in enumerate(picks)}
    reasons = {p["story_id"]: p["pin_reasons"] for p in picks}
    story_ids = list(order)

    stories = {
        story.id: (story, corro)
        for story, corro in session.execute(
            select(StoryRow, StoryCorroborationRow)
            .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
            .where(StoryRow.id.in_(story_ids))
        ).all()
    }

    checks: dict[int, dict[str, str]] = {}
    for check in session.execute(
        select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
    ).scalars():
        checks.setdefault(check.story_id, {})[check.claim_type] = check.verdict

    gists: dict[int, StoryGistRow] = {}
    for g in session.execute(
        select(StoryGistRow).where(
            StoryGistRow.story_id.in_(story_ids),
            StoryGistRow.method_version == enrich.METHOD_VERSION,
        )
    ).scalars():
        gists[g.story_id] = g

    out = []
    for sid in sorted(order, key=lambda s: order[s]):
        if sid not in stories:
            continue
        story, corro = stories[sid]
        row = _story_payload(story, corro, checks.get(sid, {}), gists.get(sid))
        row["pin_reasons"] = reasons[sid]
        out.append(row)
    return out
```

Add the import beside the other `app.stories` imports at the top of `app/api.py`:

```python
from app.stories import developing
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_api_developing.py -v`
Expected: 3 passed.

- [ ] **Step 7: Full backend gates, commit**

```bash
ruff check .
ruff format --check .
pytest -q
git add app/api.py tests/test_api_developing.py
git commit -m "feat(api): #449 GET /stories/developing with pin reasons"
```

---

### Task 3: Situation card block

**Files:**
- Modify: `osint-frontend/lib/analytics.ts` — add `PinReasons`, `DevelopingStory`, `fetchDevelopingStories` beside `fetchTopStories` (`osint-frontend/lib/analytics.ts:83-87`)
- Modify: `osint-frontend/lib/situation.ts` — add `excludePinned`
- Modify: `osint-frontend/components/panels/SituationPanel.tsx` — add `DevelopingBlock`, wire the SWR read, filter the list
- Test: `osint-frontend/__tests__/situation.test.ts` (extend)

**Interfaces:**
- Consumes: the `GET /stories/developing` payload from Task 2.
- Produces:
  ```ts
  export interface PinReasons {
    max_severity: number
    countries: number
    new_members_12h: number
    age_hours: number
  }
  export interface DevelopingStory extends StoryRow { pin_reasons: PinReasons }
  export async function fetchDevelopingStories(limit?: number): Promise<DevelopingStory[]>
  export function excludePinned<T extends { id: string }>(rows: T[], pinnedIds: string[]): T[]
  ```

- [ ] **Step 1: Write the failing test**

Append to `osint-frontend/__tests__/situation.test.ts` (and add `excludePinned` to the
existing `@/lib/situation` import list at the top of that file):

```ts
describe("excludePinned", () => {
  const rows = [{ id: "1" }, { id: "2" }, { id: "3" }]

  it("drops pinned rows so no story renders twice", () => {
    expect(excludePinned(rows, ["2"])).toEqual([{ id: "1" }, { id: "3" }])
  })

  it("returns the list untouched when nothing is pinned", () => {
    expect(excludePinned(rows, [])).toEqual(rows)
  })

  it("ignores pinned ids that are not in the list", () => {
    expect(excludePinned(rows, ["99"])).toEqual(rows)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd osint-frontend && pnpm vitest run __tests__/situation.test.ts`
Expected: FAIL — `excludePinned is not exported by @/lib/situation`

- [ ] **Step 3: Implement `excludePinned`**

Add to `osint-frontend/lib/situation.ts`:

```ts
/**
 * Drop the pinned stories from the activity list (#449). The DEVELOPING block
 * already shows them; without this they appear twice.
 */
export function excludePinned<T extends { id: string }>(rows: T[], pinnedIds: string[]): T[] {
  if (pinnedIds.length === 0) return rows
  const pinned = new Set(pinnedIds)
  return rows.filter((row) => !pinned.has(row.id))
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd osint-frontend && pnpm vitest run __tests__/situation.test.ts`
Expected: PASS

- [ ] **Step 5: Add the fetch layer**

In `osint-frontend/lib/analytics.ts`, directly below `fetchTopStories`:

```ts
/** Why a story earned the pinned slot (#449) — shown, not just asserted. */
export interface PinReasons {
  max_severity: number
  countries: number
  new_members_12h: number
  age_hours: number
}

export interface DevelopingStory extends StoryRow {
  pin_reasons: PinReasons
}

export async function fetchDevelopingStories(limit = 3): Promise<DevelopingStory[]> {
  const res = await fetch(`${API_BASE}/stories/developing?limit=${limit}`)
  if (!res.ok) throw new Error(`GET /stories/developing ${res.status}`)
  return (await res.json()) as DevelopingStory[]
}
```

- [ ] **Step 6: Render the block**

In `osint-frontend/components/panels/SituationPanel.tsx`:

Extend the existing `@/lib/analytics` import to include `fetchDevelopingStories` and
`type DevelopingStory`; extend the `@/lib/situation` import to include `excludePinned`.

Add above `StoryLine`:

```tsx
/**
 * The pinned slot (#449): multi-day international stories still gathering
 * coverage. Nothing qualifying → nothing rendered, because an empty slot is
 * itself the finding. Corroboration shows on the row and never gates the pin.
 */
function DevelopingBlock({
  stories,
  onOpen,
}: {
  stories: DevelopingStory[]
  onOpen: (id: string) => void
}) {
  if (stories.length === 0) return null
  return (
    <div className="mb-2 border-b border-neutral-800 pb-2">
      <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-amber-500/80">
        developing
      </div>
      {stories.map((s) => (
        <button
          key={s.id}
          onClick={() => onOpen(s.id)}
          className="mb-1 block w-full text-left"
        >
          <div className="flex items-baseline gap-2">
            <span className="shrink-0 text-amber-500/80">●</span>
            <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-neutral-100">
              {s.title}
            </span>
          </div>
          <div className="pl-4 font-mono text-[9px] text-neutral-500">
            {s.outlet_count} outlets · {s.pin_reasons.countries} countries ·{" "}
            {s.pin_reasons.age_hours}h ·{" "}
            {s.corroboration === null
              ? "unscored"
              : `corrob ${s.corroboration.toFixed(2)}`}{" "}
            · {s.owner_count} owners
          </div>
        </button>
      ))}
    </div>
  )
}
```

Inside the panel body, beside the existing stories SWR read, add:

```tsx
  const { data: pinned } = useSWR("stories-developing", () => fetchDevelopingStories(3), {
    refreshInterval: STORIES_REFRESH_MS,
  })
```

Then change the list derivation (`SituationPanel.tsx:309-312`) to exclude the pins:

```tsx
  const developing = pinned ?? []
  const sorted = excludePinned(
    sortByActivity(stories ?? []),
    developing.map((s) => s.id),
  )
  const { recent, older } = splitRecent(sorted)
  //: A quiet spell must not blank the card — with nothing recent, show all.
  const rows = showOlder || recent.length === 0 ? sorted : recent
```

And render the block immediately after the narrative `h2` (`SituationPanel.tsx:335-337`),
before the story rows:

```tsx
        <DevelopingBlock stories={developing} onOpen={openStory} />
```

- [ ] **Step 7: Verify the frontend builds and the suite passes**

```bash
cd osint-frontend
pnpm vitest run
pnpm lint
pnpm build
```
Expected: tests pass, lint clean, build succeeds.

- [ ] **Step 8: Commit**

```bash
git add osint-frontend/lib/analytics.ts osint-frontend/lib/situation.ts \
        osint-frontend/components/panels/SituationPanel.tsx \
        osint-frontend/__tests__/situation.test.ts
git commit -m "feat(situation): #449 pinned developing block above the activity list"
```

**Visual verification:** there is no browser automation or DOM test infrastructure in
this repo, so the rendered block ships unverified. Say so in the PR and ask Basil to
look at the card.

---

### Task 4: Re-calibrate after the regrade

Do this only once `#597` reports complete (~25.9k rows carrying `news-llm-v1`).

**Files:**
- Modify: `app/stories/developing.py` (constants + docstring), only if the numbers move
- Modify: `docs/superpowers/specs/2026-07-26-developing-pins-design.md` (Known limitation section)

- [ ] **Step 1: Confirm the regrade finished**

```bash
docker compose exec -T postgres psql -U osint -d osint -tAc \
  "SELECT count(*) FROM events WHERE payload->>'severity_method'='news-llm-v1';"
```
Expected: ~25,855 and no `grade_run` process in `ps aux`.

- [ ] **Step 2: Re-run the selector against live data**

```bash
docker compose exec -T api python -c "
from app.db import SessionLocal
from app.stories.developing import select_developing
with SessionLocal() as s:
    for r in select_developing(s, limit=10): print(r)
"
```
(If `app.db` exposes the session factory under another name, check the imports at the
top of `app/api.py` and use whatever `get_session` depends on.)

- [ ] **Step 3: Judge the output**

Check the France wildfires case specifically — it should now clear `max_severity >= 0.6`.
Confirm no obvious junk (sports, awards, appointments, heritage listings) appears in the
top 3. If junk appears, tighten `MIN_MAX_SEVERITY` to 0.7 or `MIN_COUNTRIES` to 4, re-run,
and record the before/after in the docstring. If the top 3 are all legitimate, change
nothing but note the confirmation.

- [ ] **Step 4: Update the docstring and spec, commit**

Replace the "Calibrated 2026-07-26 … ~23.3k of ~25.9k rows" paragraph with the
full-coverage numbers and the date. Update the spec's Known limitation section to
record the outcome. Commit:

```bash
git add app/stories/developing.py docs/superpowers/specs/2026-07-26-developing-pins-design.md
git commit -m "chore(stories): #449 confirm pin thresholds at full severity coverage"
```

---

### Task 5: Ship it

- [ ] **Step 1: Squash to one commit**

The 1:1:1 rule is one issue → one branch → one PR → one commit.

```bash
git reset --soft $(git merge-base HEAD origin/main)
git commit -m "$(cat <<'EOF'
feat(situation): #449 pin developing international stories above the list

The card's best real estate was ordered by last_seen, so a Tour de France
stage report outranked a widening war. The rule in the issue body (age +
fresh + high outlet_count) does not fix that — measured against live data it
pins a Mount Olympus Unesco listing at #2 and Pogacar at #5.

Pins on four gates instead: max member severity >= 0.6, >= 3 distinct member
countries, >= 1 member added in 12h, first_seen >= 24h old. Ranked by
velocity, so the slot tracks what is moving. On the calibration snapshot the
gates returned four candidates, all legitimate, and rejected every false pin
the naive rule produced.

Corroboration is shown on each pinned row and gates nothing: a widely-told
story with few independent owners is exactly what this system exists to
surface, so suppressing it would work against the point.

Nothing qualifying renders nothing — an empty slot is the finding, and the
thresholds are never relaxed to fill it.
EOF
)"
```

- [ ] **Step 2: Verify the gates one last time**

```bash
ruff check . && ruff format --check . && pytest -q
cd osint-frontend && pnpm vitest run && pnpm lint && pnpm build
```
Expected: all green. Do not open the PR on a red gate.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/449-developing-pins
gh pr create --title "feat(situation): #449 pin developing international stories above the list" --body "..."
```

The PR body must state: what the naive rule pinned and why it was rejected, the four
gates with their calibration numbers, that corroboration is shown and not gated, the
France-wildfires false negative and its cause, and that the rendered block is visually
unverified because the repo has no browser automation — asking Basil to look at the card.

Do **not** merge. Basil merges every PR himself.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 selector, four gates, ranking, constants + calibration docstring | Task 1 |
| §2 endpoint, `/stories/top` row shape, `pin_reasons`, empty 200 | Task 2 |
| §3 `DevelopingBlock`, placement under h2, SWR 60 s, pop-out, de-dup, null render | Task 3 |
| §4 backend gate tests, frontend filter + null render tests | Tasks 1–3 |
| Known limitation — re-calibrate at full coverage | Task 4 |

**Placeholder scan:** no TBDs. Every code step carries real code. Task 4 Step 3 is a
judgement step, and its decision rule (which constant to tighten, and to what) is
stated rather than left open. The one `--body "..."` is expanded by the paragraph
directly beneath it.

**Type consistency:** `select_developing` returns `story_id` / `pin_reasons` in Task 1
and is consumed under those exact keys in Task 2. `pin_reasons` fields
(`max_severity`, `countries`, `new_members_12h`, `age_hours`) match across the Python
dict, the pytest assertions, the `PinReasons` interface, and the JSX. `_story_payload`
has one signature, used by both routes. `excludePinned` is declared, implemented, and
tested with the same generic constraint.
