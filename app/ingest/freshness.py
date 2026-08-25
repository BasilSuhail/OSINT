"""Reject events that are not current, at the live ingest boundary (#571).

The system's claim is current news. Nothing enforced the "current" half: a feed
could hand us anything and we stored it. `rss-cnn-world` served evergreen promo
entries — "Donate now to a Top 10 CNN Hero" — dated 2021, and 79% of its rows
were over a thousand days old at ingest.

Three rules shape this, and all three come from measurement rather than taste.

**The bound is per class, because one number cannot be right for everything.**
FRED history reaches 385 days at ingest and yfinance 7; historical depth is the
entire point of those sources, so they are unbounded. urlhaus publishes a
rolling window measured at p99 30.3 days, so it needs headroom above that.

**The bound for news and hazard is whatever retention is.** The rule becomes
"do not ingest what retention would immediately delete", which is defensible
where an arbitrary number is not — and that was literally happening.
Housekeeping deleted the same 23 rss-cnn-world rows on three consecutive days
while the hourly fetch re-inserted them, an endless churn that retention could
never win because the feed re-supplied the junk faster than the daily prune
removed it. The boundary is the only place that loop can be broken.

**A naive 7-day rule would have been wrong.** Measured p99 ingest lag:
rss-jpost-world 19.3 days, rss-responsible-statecraft 12.0, rss-guardian-world
9.6 — all legitimate slow publishing. Being too strict silently deletes real
news, which is a worse failure than the one being fixed.

A rule survives a settings change; a number does not. Retention is
env-overridable and a board with a larger disk raises it — a year rather than a
month — so the bounds are read from the retention policy rather than restated
here. Restating it meant the window could only ever fill going forward: the
prune would keep a year and the gate would still refuse anything over 30 days
at the door, with nothing on screen saying why.

This applies to the live fetch path only. Backfills legitimately insert old
rows and never pass through here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.housekeeping import retention_days
from app.models import Event
from app.settings import settings

#: The bound when retention has no window to lend — the storage rule is off and
#: the disk budget is the only thing deleting anything (`RETENTION_*_DAYS=0`).
#:
#: Retention and currency were the same number for as long as retention was
#: always a number, and switching the storage clock off switched this gate off
#: with it. That is the wrong consequence: how long an event is *kept* and how
#: old an event may be to count as *current* are different questions, and only
#: the first one an operator answers with a disk budget.
#:
#: Six months, and the reasoning is the measurement above rather than taste.
#: The worst legitimate publishing lag measured on any feed here is p99 19.3
#: days, so this is roughly nine times the slowest real news and cannot be what
#: refuses a story. It still refuses the evergreen class the module was written
#: for — promo entries dated years back, republished forever.
NO_RETENTION_MAX_AGE: timedelta = timedelta(days=180)

#: Sources whose value IS their history. Bounding these would defeat them.
UNBOUNDED_SOURCES: frozenset[str] = frozenset(
    {
        "fred",
        "yfinance",
        "emdat",
        "acled",
        "polymarket",
        # Published as monthly releases, so an item is routinely a month or
        # more old before it is available at all.
        "uk-police",
        # Only currently-active hazards are listed at all — the fetcher drops
        # anything the feed marks not-current before it reaches here — so a
        # GDACS event's age is its onset, not its staleness. A flood that began
        # in spring and is still running is the most current thing the feed has
        # to say, and bounding it on the retention window would refuse to
        # collect the long-running hazards this source exists to report.
        "gdacs",
    }
)

#: Cyber feeds republish a rolling window of older indicators, so their bound
#: is the retention window plus this. urlhaus measured p99 30.3 days at ingest
#: against a 30-day window, and the headroom is what puts the bound clear of
#: that republished tail — 45 days at the default. It is a property of the
#: feed's behaviour rather than of the window, so it stays a constant while the
#: window moves, and stays named so the measurement behind it is still legible.
CYBER_REPUBLISH_HEADROOM: timedelta = timedelta(days=15)
_CYBER_PREFIX = "abuse-ch-"

#: Feeds disagree with our clock by minutes routinely. Beyond this, a future
#: date is a parsing or timezone defect worth surfacing.
MAX_FUTURE_SKEW: timedelta = timedelta(hours=2)

#: Kept short: this ends up in a log line and a failure row, not a report.
_SAMPLE_TITLES = 2


@dataclass(frozen=True)
class Rejection:
    """One event refused at the boundary, with the reason kept for reporting."""

    event: Event
    reason: str


def retention_aligned_max_age(source: str) -> timedelta:
    """How long `source` is kept, as the age bound the gate applies to it.

    `retention_days()` is the authority on what housekeeping deletes, so it is
    asked rather than mirrored: a second copy of the mapping is a second thing
    to raise, and the one that gets forgotten is the one that silently refuses
    the news the operator asked to collect.

    A source the policy does not list falls back to the news window, which is
    what housekeeping's generic `rss-%` rule prunes it on. An unlisted source
    is also the shape the CNN promo entries arrived in, so the fallback is a
    bound and never a free pass. Keep-forever sources never reach here — they
    are answered by UNBOUNDED_SOURCES above.

    `NO_RETENTION_MAX_AGE` when the storage clock is off. The rule this gate
    enforces is "do not ingest what retention would immediately delete", and
    with no retention window there is no such age — but "current" is still a
    claim this system makes, and a gate that bounds nothing stops making it.
    """
    policy = retention_days()
    days = policy[source] if source in policy else _window_or_none(settings.retention_news_days)
    return NO_RETENTION_MAX_AGE if days is None else timedelta(days=days)


def _window_or_none(days: int) -> int | None:
    """A configured window, or None when it is switched off. Mirrors the same
    reading in `app.housekeeping`, which is the authority on the policy."""
    return days if days > 0 else None


def max_age(source: str) -> timedelta | None:
    """The oldest an event from `source` may be, or None for unbounded."""
    slug = (source or "").lower()
    if slug in UNBOUNDED_SOURCES:
        return None
    window = retention_aligned_max_age(slug)
    if slug.startswith(_CYBER_PREFIX):
        return window + CYBER_REPUBLISH_HEADROOM
    return window


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def partition(
    events: list[Event], *, now: datetime | None = None
) -> tuple[list[Event], list[Rejection]]:
    """Split `events` into those worth storing and those that are not current.

    An event with no date is kept: dropping on a missing field would silently
    lose real news, and that is a parser problem rather than a freshness one.
    """
    now = now or datetime.now(UTC)
    kept: list[Event] = []
    rejected: list[Rejection] = []
    #: The bound is read from settings now, so it is resolved once per source
    #: per batch rather than once per event: an ADS-B fetch is tens of
    #: thousands of rows that all share one source and one answer.
    bounds: dict[str, timedelta | None] = {}

    for event in events:
        occurred_at = getattr(event, "occurred_at", None)
        if occurred_at is None:
            kept.append(event)
            continue

        occurred_at = _as_aware(occurred_at)
        if occurred_at > now + MAX_FUTURE_SKEW:
            ahead = occurred_at - now
            rejected.append(
                Rejection(event, f"dated {_days(ahead)} in the future ({occurred_at.date()})")
            )
            continue

        if event.source not in bounds:
            bounds[event.source] = max_age(event.source)
        bound = bounds[event.source]
        if bound is None:
            kept.append(event)
            continue

        age = now - occurred_at
        if age > bound:
            rejected.append(Rejection(event, f"{_days(age)} old at ingest, limit {_days(bound)}"))
            continue

        kept.append(event)

    return kept, rejected


def _days(delta: timedelta) -> str:
    days = delta.total_seconds() / 86400
    return f"{days:.0f} days" if days >= 1 else f"{delta.total_seconds() / 3600:.0f} hours"


def summarize(rejections: list[Rejection]) -> str | None:
    """One line describing a batch's rejections, or None if there were none.

    Named samples on purpose: "12 rejected" tells you a feed is broken, while
    "12 rejected, e.g. 'Donate now to a Top 10 CNN Hero' 1200 days old" tells
    you why, which is the difference between a number and a diagnosis.
    """
    if not rejections:
        return None
    samples = "; ".join(
        f"{(r.event.payload or {}).get('title', '?')!r} — {r.reason}"
        for r in rejections[:_SAMPLE_TITLES]
    )
    more = (
        "" if len(rejections) <= _SAMPLE_TITLES else f" (+{len(rejections) - _SAMPLE_TITLES} more)"
    )
    return f"{len(rejections)} event(s) rejected as not current: {samples}{more}"
