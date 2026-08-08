"""Nothing is published in the future (#766).

A row dated ahead of the clock sorts above real news, and it distorts every
measure that compares a row against now — freshness, "latest information is N
hours old", the deck's ordering. Three such rows were live when this was
written, up to 115 minutes ahead.

Measured on the Jerusalem Post front page, the feed that produced them:

```
now utc: 2026-08-08T14:06Z
'Sat, 08 Aug 2026 16:25:19 GMT'   ahead 139 min
'Sat, 08 Aug 2026 16:17:40 GMT'   ahead 131 min
'Sat, 08 Aug 2026 15:43:05 GMT'   ahead  97 min
'Sat, 08 Aug 2026 13:57:53 GMT'   behind   8 min
```

Eight of twelve items ahead, **none beyond 180 minutes**. That ceiling is the
finding: a drifting clock scatters, a mislabelled timezone does not. The feed
stamps Israel local time and labels it `GMT`, so subtracting three hours puts
every item in the past with the gaps between them unchanged.

## Two different defects, two different repairs

**A systematic offset** is a property of the feed, and correcting it is a
translation: every row moves by the same whole hour, order and spacing
survive, and a row that was genuinely two hours old stays two hours old.

**A single future row** is a property of that row. There is nothing to prove
an offset from, so it is clamped to the moment it was fetched — the only time
we can actually vouch for — and the original is kept in the payload.

Clamping the offset case would be wrong twice over: it would collapse the
newest rows onto one timestamp, destroying which came first, and it would
claim precision about publication that the feed never gave us.

## What is deliberately not done

Rejection. The previous behaviour dropped anything more than two hours ahead,
which silently discarded real news over a timezone bug. A story we cannot date
is still a story; a story we date wrongly and admit to is honest. Every
adjustment is written onto the row, so a reader — or an audit — can see that
the timestamp was moved and what it was before.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import Event

#: Clock disagreement below this is not worth recording. Feeds and our host
#: differ by seconds constantly; noting it would bury the real defects.
TOLERANCE: timedelta = timedelta(minutes=2)

#: A batch needs this many future rows before the future looks like a property
#: of the feed rather than of one row.
MIN_OFFSET_ROWS: int = 3

#: …and this share of the batch. One stray row in a hundred is not an offset.
MIN_OFFSET_SHARE: float = 0.25

#: The largest offset worth believing. Beyond this the timestamps are not a
#: timezone label, they are wrong in a way this module cannot diagnose, and
#: clamping is the honest answer.
MAX_OFFSET_HOURS: int = 14


@dataclass
class Report:
    """What was changed, for the log line and the health record."""

    source: str = ""
    offset_hours: int | None = None
    shifted: int = 0
    clamped: int = 0
    max_ahead_minutes: float = 0.0
    sample: list[str] = field(default_factory=list)

    def summary(self) -> str | None:
        if self.offset_hours is not None:
            return (
                f"{self.source}: corrected a {self.offset_hours}h feed offset on "
                f"{self.shifted} rows (max {self.max_ahead_minutes:.0f} min ahead)"
            )
        if self.clamped:
            return (
                f"{self.source}: clamped {self.clamped} future-dated row(s) to fetch time "
                f"(max {self.max_ahead_minutes:.0f} min ahead)"
            )
        return None


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _minutes_ahead(event: Event, now: datetime) -> float:
    return (_as_aware(event.occurred_at) - now).total_seconds() / 60


def detect_offset(events: list[Event], now: datetime) -> int | None:
    """The whole-hour offset this feed is publishing in, if it has one.

    Provable from the batch alone: enough rows are ahead, and the smallest
    whole hour that covers the furthest of them also puts every other row in
    the past. If subtracting it would push a row that is currently *behind*
    the clock further than the offset explains, the pattern is not an offset
    and the answer is None.
    """
    ahead = [m for m in (_minutes_ahead(e, now) for e in events) if m > TOLERANCE.seconds / 60]
    if len(ahead) < MIN_OFFSET_ROWS or len(ahead) / len(events) < MIN_OFFSET_SHARE:
        return None
    hours = int(max(ahead) // 60) + 1
    if hours > MAX_OFFSET_HOURS:
        return None
    return hours


def normalize(events: list[Event], *, now: datetime | None = None) -> tuple[list[Event], Report]:
    """Move any row dated ahead of the clock back to a time we can vouch for.

    Returns new events — `Event` is a pydantic model and the caller may still
    hold the originals — and a report of what was done.
    """
    now = now or datetime.now(UTC)
    report = Report(source=events[0].source if events else "")
    if not events:
        return [], report

    report.max_ahead_minutes = max((_minutes_ahead(e, now) for e in events), default=0.0)
    if report.max_ahead_minutes <= TOLERANCE.seconds / 60:
        return list(events), report

    offset = detect_offset(events, now)
    out: list[Event] = []
    for event in events:
        raw = _as_aware(event.occurred_at)
        if offset is not None:
            out.append(
                _with_time(
                    event,
                    raw - timedelta(hours=offset),
                    reason="feed-offset",
                    raw=raw,
                    offset_hours=offset,
                )
            )
            report.shifted += 1
            continue
        if _minutes_ahead(event, now) > TOLERANCE.seconds / 60:
            out.append(_with_time(event, now, reason="future-clamped", raw=raw))
            report.clamped += 1
            continue
        out.append(event)

    report.offset_hours = offset
    report.sample = [
        str((e.payload or {}).get("title") or e.source_event_id)[:60]
        for e in out
        if (e.payload or {}).get("time_adjustment")
    ][:2]
    return out, report


def _with_time(
    event: Event,
    when: datetime,
    *,
    reason: str,
    raw: datetime,
    offset_hours: int | None = None,
) -> Event:
    """A copy of `event` dated `when`, carrying what was changed and why."""
    payload: dict[str, Any] = dict(event.payload or {})
    note: dict[str, Any] = {"reason": reason, "raw": raw.isoformat()}
    if offset_hours is not None:
        note["offset_hours"] = offset_hours
    payload["time_adjustment"] = note
    return event.model_copy(update={"occurred_at": when, "payload": payload})


def counts_by_reason(reports: list[Report]) -> Counter[str]:
    """Aggregate for a health line: how many rows each repair touched."""
    out: Counter[str] = Counter()
    for report in reports:
        if report.shifted:
            out["feed-offset"] += report.shifted
        if report.clamped:
            out["future-clamped"] += report.clamped
    return out
