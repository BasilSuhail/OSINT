"""Give mapped GDELT rows the headline of the article they came from (#788).

The parser stores a CAMEO root label and a source URL. The label is a
bucket, not a description, so the row's own article is the only honest place
a headline can come from. This walks the rows that are actually drawn on the
map and fills `payload.title` from `SOURCEURL`.

Only the rows that are drawn. Country-precision GDELT rows are never pinned
(#727) and a headline for a row nobody can click is a request spent on
nothing.
"""

from __future__ import annotations

from time import monotonic
from typing import Any, Final

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db_models import EventRow
from app.enrichment.article_title import TIMEOUT_S, USER_AGENT, fetch_title

#: Rows per run. Measured on the first live run: 20 rows in 12.65 s, so a
#: row costs ~0.63 s and sixty fit comfortably inside the five-minute beat.
#: At that rate this is ~17,280/day against a measured 1,425 to 5,064
#: city-precision rows arriving per day, which clears the 9,788-row backlog
#: in well under a day instead of nearly two, and then idles.
BATCH_LIMIT: Final[int] = 60

#: Wall-clock ceiling for one run, comfortably inside the five-minute beat.
#: The cap alone does not bound the time: sixty rows that each time out at
#: TIMEOUT_S would take 360 s, the next beat would fire mid-run, and both
#: runs would select the same rows — the attempt counter is only written at
#: the end — so every row in the overlap would be fetched twice. Stopping on
#: the clock makes that impossible however slow the batch turns out to be.
RUN_BUDGET_S: Final[float] = 240.0

#: How many times a retryable failure is worth repeating before the row is
#: left alone. A site that has timed out three times is not going to answer
#: on the fourth, and the slot is better spent on a row never tried.
MAX_ATTEMPTS: Final[int] = 3


#: Newest first. A row the reader is looking at now matters more than one
#: that will age out of the retention window before they scroll to it.
def pending_ids(session: Session, *, limit: int = BATCH_LIMIT) -> list[int]:
    """Mapped GDELT rows still missing a headline, newest first.

    Written in SQLAlchemy expressions rather than raw SQL so it runs on
    SQLite as well as Postgres — the JSON accessors compile to `->>` on one
    and `json_extract` on the other, and the tests can then exercise the
    selection rules, which are the part worth testing.
    """
    payload = EventRow.payload
    attempts = payload["title_attempts"].as_integer()
    stmt = (
        select(EventRow.id)
        .where(
            EventRow.source == "gdelt",
            #: Country-precision rows are never pinned (#727), so a headline
            #: for one is a request spent on a marker nobody can click.
            payload["geo_precision"].as_string() == "city",
            #: Rows stored before #733 carry a 14-digit DATEADDED here. They
            #: must never become outbound requests.
            payload["source_url"].as_string().like("http%"),
            payload["title"].as_string().is_(None),
            or_(attempts.is_(None), attempts < MAX_ATTEMPTS),
            or_(
                payload["title_status"].as_string().is_(None),
                payload["title_status"].as_string() != "gave-up",
            ),
        )
        .order_by(EventRow.occurred_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def _record(event: EventRow, *, title: str | None, reason: str, retryable: bool) -> None:
    """Write the outcome onto the row, including the failures.

    A failure is stored, not just skipped. Without the attempt count the same
    dead link is re-fetched every beat forever, and the rows behind it are
    never reached.
    """
    payload: dict[str, Any] = dict(event.payload or {})
    attempts = int(payload.get("title_attempts") or 0) + 1
    payload["title_attempts"] = attempts
    if title:
        payload["title"] = title
        payload["title_source"] = "article"
        payload["title_status"] = "ok"
    else:
        payload["title_status"] = reason if retryable and attempts < MAX_ATTEMPTS else "gave-up"
        payload["title_reason"] = reason
    event.payload = payload
    #: The column is JSON: SQLAlchemy compares by identity, and a dict that
    #: was rebound still needs saying so explicitly for mutation-tracking
    #: setups where the same object comes back.
    flag_modified(event, "payload")


def enrich_titles(
    session: Session,
    *,
    limit: int = BATCH_LIMIT,
    budget_s: float = RUN_BUDGET_S,
) -> dict[str, int]:
    """Fill `payload.title` for up to `limit` mapped GDELT rows.

    Stops at `limit` rows or `budget_s` seconds, whichever comes first.

    Sequential, one connection reused across the batch: this runs beside the
    fetchers on a small box, and sixty parallel requests to sixty news sites
    is a different kind of neighbour to be. Sequential is also what keeps the
    request rate self-limiting — one in flight, never a burst.
    """
    ids = pending_ids(session, limit=limit)
    if not ids:
        return {"considered": 0, "titled": 0, "failed": 0, "ran_out_of_time": 0}

    events = list(session.execute(select(EventRow).where(EventRow.id.in_(ids))).scalars())
    titled = 0
    failed = 0
    considered = 0
    deadline = monotonic() + budget_s
    with httpx.Client(
        timeout=TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        for event in events:
            #: Out of time. The rows not reached are untouched — no attempt
            #: recorded, nothing to undo — and the next beat picks them up
            #: first, because the ordering is stable.
            if monotonic() >= deadline:
                break
            considered += 1
            url = (event.payload or {}).get("source_url") or ""
            result = fetch_title(url, client=client)
            _record(event, title=result.title, reason=result.reason, retryable=result.retryable)
            if result.title:
                titled += 1
            else:
                failed += 1
    session.commit()
    return {
        "considered": considered,
        "titled": titled,
        "failed": failed,
        #: Surfaced rather than silent: a run that keeps stopping early is
        #: how a slow batch would otherwise hide.
        "ran_out_of_time": len(events) - considered,
    }
