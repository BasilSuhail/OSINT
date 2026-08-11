"""Which stories earn the Situation card's pinned slot (#449).

Declared mechanics, no tuning at read time. A story is "developing" when
four things hold at once:

    max(member severity) >= 0.6     it is about harm, not a heritage listing
    distinct member countries >= 3  the world is telling it, not one capital
    >= 1 member added in 12 h       coverage is still arriving
    first_seen at least 24 h ago    it has lasted more than one news cycle

Ranked velocity first, so the pin tracks what is *moving*, not what is
merely large. Corroboration is deliberately absent from every gate: a
widely-told story with few independent owners is exactly what the card must
keep visible (#363/#365, #641), so it is displayed alongside the pin rather
than used to suppress it.

Re-checked 2026-07-26 at 98.4% coverage (25,433 of ~25,855 rows) while the #597
severity regrade was still finishing (~400 rows remaining). The thresholds are
confirmed unchanged; the gates returned the same four candidates as at 90% coverage
(West Bank arrests, Romania/drone, Typhoon Noul, Iran/Ukraine) and again rejected
the naive outlet-count rule's false pins: Mount Olympus Unesco listing, Tour de
France stage report, Indian cabinet appointment. The known false negative persists:
France wildfires (42,000 hectares, 220,000 evacuated) fails at max severity 0.5
with only 2 distinct countries because 15 of its 22 members carry the new grade.
Country spread is the binding gate, and it is less binding than it was: at the
2026-07-26 check 69.9% of story members carried NULL events.country, and
re-measured 2026-08-11 that is 17.4% (3,329 of 4,029 members in a 48h window
now resolve). The selector stays conservative by design, but the gate it leans
on is no longer mostly missing data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryMemberRow, StoryRow

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


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; Postgres aware ones in the session's zone."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
        .order_by(
            new_members.desc(),
            countries.desc(),
            StoryRow.outlet_count.desc(),
            StoryRow.id.desc(),
        )
        .limit(limit)
    )

    return [
        {
            "story_id": row.id,
            "pin_reasons": {
                "max_severity": row.max_severity,
                "countries": row.countries,
                "new_members_12h": int(row.new_members),
                "age_hours": int((now - _as_utc(row.first_seen)).total_seconds() // 3600),
            },
        }
        for row in session.execute(stmt).all()
    ]
