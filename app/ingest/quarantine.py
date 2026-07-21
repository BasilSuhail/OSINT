"""Stop retrying a feed that cannot succeed (#567).

`ingest_failures` reached 6,910 rows, much of it a handful of feeds that could
never have worked: `rss-arab-news` answered 403 on every attempt for a week,
`rss-nation-kenya` 404. Because `run_fetcher` is declared
`autoretry_for=(Exception,)` with `max_retries=5`, each hourly tick of a dead
feed cost six requests — roughly 144 a day, forever.

The distinction that was missing: a 403 or 404 is a statement about the
*resource*, while a timeout or a 502 is a statement about the *moment*.
Retrying both on the same schedule is what turned a dead URL into hundreds of
rows of noise.

Nothing is disabled permanently. A quarantined source is skipped until its
retry time, then tried again; any success clears the record at once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_models import SourceQuarantineRow

Kind = Literal["permanent", "throttled"]

#: The resource is gone, forbidden, or was never there. Time does not help.
PERMANENT_STATUSES: frozenset[int] = frozenset({401, 403, 404, 410})

#: A real "later" rather than a "never".
THROTTLED_STATUS: int = 429

#: Escalation per consecutive failure. A dead URL is checked rarely; a
#: throttled one recovers on its own and is checked sooner.
_SCHEDULE: dict[Kind, tuple[timedelta, ...]] = {
    "permanent": (
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(days=1),
        timedelta(days=3),
        timedelta(days=7),
    ),
    "throttled": (
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(days=1),
    ),
}

MAX_BACKOFF: timedelta = timedelta(days=7)

DETAIL_MAX_CHARS = 300


def classify(exc: BaseException) -> Kind | None:
    """Which quarantine a failure earns, or None to leave it transient."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    status = exc.response.status_code
    if status in PERMANENT_STATUSES:
        return "permanent"
    if status == THROTTLED_STATUS:
        return "throttled"
    return None


def backoff_for(kind: Kind, consecutive_failures: int) -> timedelta:
    """How long to wait before trying `kind` again after N failures."""
    steps = _SCHEDULE[kind]
    index = min(max(consecutive_failures, 1), len(steps)) - 1
    return min(steps[index], MAX_BACKOFF)


def _retry_after_delta(exc: BaseException) -> timedelta | None:
    """The host's own `Retry-After`, when it sends a usable one."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    raw = exc.response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return timedelta(seconds=float(raw))
    except ValueError:  # HTTP-date form; the schedule covers it
        return None


def record_failure(
    session: Session, *, source: str, exc: BaseException, now: datetime | None = None
) -> SourceQuarantineRow | None:
    """Quarantine `source` if this failure earns it. Returns the row, or None.

    Transient faults are left entirely alone: Celery's retries exist for them.
    """
    kind = classify(exc)
    if kind is None:
        return None

    now = now or datetime.now(UTC)
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    row = session.get(SourceQuarantineRow, source)
    failures = (row.consecutive_failures + 1) if row is not None else 1

    wait = backoff_for(kind, failures)
    header_wait = _retry_after_delta(exc)
    if header_wait is not None:
        wait = max(wait, header_wait)

    detail = f"HTTP {status}: {exc}"[:DETAIL_MAX_CHARS] if status else str(exc)[:DETAIL_MAX_CHARS]

    if row is None:
        row = SourceQuarantineRow(
            source=source,
            kind=kind,
            http_status=status,
            detail=detail,
            consecutive_failures=1,
            first_failed_at=now,
            last_failed_at=now,
            retry_after=now + wait,
        )
        session.add(row)
    else:
        row.kind = kind
        row.http_status = status
        row.detail = detail
        row.consecutive_failures = failures
        row.last_failed_at = now
        row.retry_after = now + wait
    session.flush()
    return row


def record_success(session: Session, *, source: str) -> None:
    """Clear any quarantine — the source is answering again."""
    session.execute(delete(SourceQuarantineRow).where(SourceQuarantineRow.source == source))


def skip_reason(session: Session, source: str, *, now: datetime | None = None) -> str | None:
    """Why this source should not be fetched right now, or None to go ahead."""
    row = session.execute(
        select(SourceQuarantineRow).where(SourceQuarantineRow.source == source)
    ).scalar_one_or_none()
    if row is None:
        return None
    now = now or datetime.now(UTC)
    retry_after = row.retry_after
    if retry_after.tzinfo is None:  # SQLite hands back naive datetimes
        retry_after = retry_after.replace(tzinfo=UTC)
    if retry_after <= now:
        return None
    return (
        f"quarantined ({row.kind}) after {row.consecutive_failures} failures — "
        f"{row.detail}; next attempt {retry_after.isoformat()}"
    )
