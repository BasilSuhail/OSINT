"""Which stories earn the Situation card's pinned slot (#449).

Declared mechanics, no tuning at read time. A story is "developing" when
four things hold at once:

    max(member severity) >= 0.6     it is about harm, not a heritage listing
    >= 3 independent owners         the world is telling it, not one newsroom
    >= 1 member added in 12 h       coverage is still arriving
    first_seen at least 24 h ago    it has lasted more than one news cycle

Ranked velocity first, so the pin tracks what is *moving*, not what is
merely large.

The owner gate is the one place independence decides anything (#1031). Every
other surface keeps the #363/#365 and #641 rule: a widely-told story with few
independent owners is exactly what must stay *visible*, and it does — it sits
in /stories/top with its corroboration score shown beside it, never suppressed
by it. The pinned slot asks a narrower question. There is one of it, above
everything else, and the claim it makes on the reader's behalf is "the world
is telling this". That claim is about tellers, so the slot counts tellers.

Re-checked 2026-07-26 at 98.4% coverage (25,433 of ~25,855 rows) while the #597
severity regrade was still finishing (~400 rows remaining). The thresholds are
confirmed unchanged; the gates returned the same four candidates as at 90% coverage
(West Bank arrests, Romania/drone, Typhoon Noul, Iran/Ukraine) and again rejected
the naive outlet-count rule's false pins: Mount Olympus Unesco listing, Tour de
France stage report, Indian cabinet appointment. The known false negative persists:
France wildfires (42,000 hectares, 220,000 evacuated) fails at max severity 0.5
because 15 of its 22 members carry the new grade.

The country gate those checks describe was removed 2026-08-19 (#1031). It
counted `distinct events.country`, which answers "which country is this story
about" and not "who is telling it" (`app/sources/rss_news_fetcher.py`); every
member of a story about one place resolves to that one place however many
newsrooms filed, so the slot stood empty almost always. Counts under
MIN_OWNERS. Country is still measured and still reported beside the pin, and
it resolves far better than it once did: 69.9% of story members carried NULL
events.country at the 2026-07-26 check, and 17.4% (3,329 of 4,029 members in a
48h window) re-measured 2026-08-11. It is evidence for the reader now, not a
gate.
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
#: Independent tellers, from `StoryRow.owner_count` — owners, not outlets, so
#: several feeds under one parent count once (`app/stories/independence.py`).
#: Measured on a live board 2026-08-19: 27 stories in the candidate pool (fresh
#: within 6 h, first seen at least 24 h ago), of which 7 cleared severity and
#: velocity, and 5 of those 7 pin at three owners. Owners and outlets agreed at
#: 3 across that pool — nothing was passing on several feeds from one parent —
#: so the stricter of the two measures cost nothing on the day and holds as
#: feeds are added. The country gate this replaces passed 1 of the 27, and 0 in
#: combination with the others (#1031).
MIN_OWNERS: int = 3
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
        .where(
            StoryRow.last_seen >= fresh_cutoff,
            StoryRow.first_seen <= age_cutoff,
            StoryRow.owner_count >= MIN_OWNERS,
        )
        # `outlet_count` is grouped because the ranking below still names it;
        # `owner_count` needs no grouping of its own, being one value per story
        # and so a row predicate rather than an aggregate one.
        .group_by(StoryRow.id, StoryRow.first_seen, StoryRow.outlet_count)
        .having(max_severity >= MIN_MAX_SEVERITY)
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
