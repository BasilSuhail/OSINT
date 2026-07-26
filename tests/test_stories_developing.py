"""Selection rule for the pinned developing stories (#449)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryMemberRow, StoryRow
from app.stories.developing import _as_utc, select_developing

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
    for i, country in enumerate(("IN", "IN", "LK")):
        _member(db_session, sid, severity=0.8, country=country, added_hours=2 + i)
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
        _member(db_session, sid, severity=0.7, country=country, added_hours=2)
    assert select_developing(db_session, now=NOW) == []


def test_ranks_by_velocity_then_spread_then_outlets(db_session: Session) -> None:
    # Test primary sort (velocity): both stories have 4 members in 12h window
    # First story: 4 members across 4 distinct countries
    vel4_country4 = _story(db_session, title="vel4_country4", outlet_count=2)
    for i, country in enumerate(("IR", "UA", "RO", "PL")):
        _member(db_session, vel4_country4, severity=0.6, country=country, added_hours=1 + i)

    # Second story: 4 members across only 3 distinct countries (IR appears twice)
    # Tests that countries tie-breaker works: 4 countries beats 3 countries
    vel4_country3 = _story(db_session, title="vel4_country3", outlet_count=3)
    members_config = [("IR", 1), ("IR", 2), ("UA", 3), ("RO", 4)]
    for country, added_hours in members_config:
        _member(db_session, vel4_country3, severity=0.6, country=country, added_hours=added_hours)

    # Test secondary sort (countries tie-breaker, already verified above)
    # Test tertiary sort (outlet_count): two stories with equal velocity and countries.
    # Seed the 10-outlet story first so its id is LOWER than the 5-outlet story's.
    # The final stability key is `id DESC` (higher id wins ties), so id order
    # alone would rank the 5-outlet story here instead — disagreeing with the
    # asserted result below. Only a working `outlet_count DESC` key can produce
    # the ranking this test asserts.
    # Third story: 2 members in the 12h window (one outside it), 3 countries, 10 outlets
    vel2_country3_big = _story(db_session, title="vel2_country3_big", outlet_count=10)
    for i, country in enumerate(("FR", "BE", "ES")):
        # One outside window to get velocity=2
        _member(
            db_session,
            vel2_country3_big,
            severity=0.6,
            country=country,
            added_hours=13 if i == 0 else 1 + i,
        )

    # Fourth story: 2 members in the 12h window, 3 countries, 5 outlets
    # Tie-breaker test: 10 outlets beats 5 outlets, even though this story
    # was seeded later and so has the higher id.
    vel2_country3_small = _story(db_session, title="vel2_country3_small", outlet_count=5)
    for i, country in enumerate(("DE", "AT", "GB")):
        # One outside window to get velocity=2
        _member(
            db_session,
            vel2_country3_small,
            severity=0.6,
            country=country,
            added_hours=13 if i == 0 else 1 + i,
        )

    rows = select_developing(db_session, now=NOW)
    story_ids = [r["story_id"] for r in rows]

    # Velocity=4 stories rank first (primary sort)
    # Among velocity=4, vel4_country4 (4 countries) beats vel4_country3 (3 countries)
    assert story_ids[0] == vel4_country4

    # vel4_country3: velocity=4 but only 3 countries
    assert story_ids[1] == vel4_country3

    # vel2_country3_big: velocity=2 but higher outlets than vel2_country3_small,
    # despite having the LOWER id (seeded first) — only outlet_count DESC
    # explains this ranking; id DESC alone would put the small story here instead.
    assert story_ids[2] == vel2_country3_big
    assert len(story_ids) == 3


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


def test_as_utc_tags_naive_datetime_unchanged() -> None:
    """SQLite hands back naive datetimes — they are the session's own clock, so
    tagging with UTC must not shift the wall-clock value at all."""
    naive = datetime(2026, 7, 26, 10, 0)
    result = _as_utc(naive)
    assert result == datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    assert result.hour == 10


def test_as_utc_converts_aware_non_utc_datetime() -> None:
    """Postgres can hand back aware datetimes in the session's timezone. A
    +01:00 wall-clock of 11:00 is 10:00 UTC — `_as_utc` must actually convert,
    not just relabel the tzinfo (an earlier bug did `.replace(tzinfo=UTC)`,
    which would have left this at 11:00 UTC)."""
    aware = datetime(2026, 7, 26, 11, 0, tzinfo=timezone(timedelta(hours=1)))
    result = _as_utc(aware)
    assert result == datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
    assert result.hour == 10
    assert result.tzinfo == UTC
