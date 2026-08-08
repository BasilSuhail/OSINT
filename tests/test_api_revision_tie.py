"""Paging across a migration-sized revision tie (#764).

Migration 0026 stamped 1,489,591 rows with a single `updated_at`, and the live
table still carries that tie:

```
updated_at                       rows
2026-08-03 14:31:50.272366+00    1,489,591
2026-08-07 07:20:04.919329+00        5,256
```

PostgreSQL's `now()` is transaction-scoped, so a tie this size is not an
accident of one migration — any bulk write produces one. A cursor that pages
on the timestamp alone either loops forever on the first page or skips the
rest of the tie, and 745 pages is enough of either to matter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import EventRow

TIE = datetime(2026, 8, 3, 14, 31, 50, 272366, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _seed(session, n: int) -> None:
    session.add_all(
        [
            EventRow(
                source="gdelt",
                source_event_id=f"tied-{i}",
                occurred_at=TIE - timedelta(days=30),
                fetched_at=TIE,
                updated_at=TIE,
                category="geopolitical",
                keywords=[],
                lat=1.0,
                lon=1.0,
                payload={"title": f"story {i}"},
            )
            for i in range(n)
        ]
    )
    session.commit()


def _page(client, *, since: str, after_id: str | None, limit: int) -> list[dict]:
    #: Passed as params rather than spliced into the path: an unencoded "+"
    #: in the offset arrives as a space and the timestamp fails to parse.
    params: dict[str, str | int] = {"updated_since": since, "limit": limit}
    if after_id is not None:
        params["updated_after_id"] = after_id
    return client.get("/events", params=params).json()


def test_the_whole_tie_is_reachable_one_page_at_a_time(db_session):
    _seed(db_session, 25)
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    since = (TIE - timedelta(seconds=1)).isoformat()
    seen: list[str] = []
    after_id: str | None = None
    for _ in range(10):
        page = _page(client, since=since, after_id=after_id, limit=10)
        if not page:
            break
        seen.extend(row["source_event_id"] for row in page)
        since = page[-1]["updated_at"]
        after_id = page[-1]["id"]

    assert len(seen) == 25, "the tie was not fully paged"
    assert len(set(seen)) == 25, "a row was served twice"


def test_a_cursor_inside_the_tie_advances(db_session):
    """Without the id half of the cursor this returns the same page forever."""
    _seed(db_session, 12)
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)

    first = _page(client, since=(TIE - timedelta(seconds=1)).isoformat(), after_id=None, limit=5)
    second = _page(client, since=first[-1]["updated_at"], after_id=first[-1]["id"], limit=5)
    assert {r["id"] for r in first}.isdisjoint({r["id"] for r in second})


def test_the_id_cursor_requires_its_timestamp(db_session):
    """A bare id is not a position in a tie, and guessing one would skip rows."""
    app.dependency_overrides[get_session] = lambda: db_session
    assert TestClient(app).get("/events", params={"updated_after_id": 5}).status_code == 200
