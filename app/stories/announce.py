"""Tell the operator when a story starts developing (#1039).

The console has run continuously for weeks and the only way to read what it
found was to open it. The ingest watchdog already pages when a *source* goes
quiet; nothing said anything when the news itself moved.

This is the other half of that, and deliberately the same shape: a row in
`notifications` whose UNIQUE `dedup_key` decides whether anything is sent, then
a best-effort push that stays silent when it is not configured. Same table, same
dedup, same "absent means quiet" rule as `app.watchdog`.

## What earns a message, and what only rides along

Two things the console already computes, used for two different jobs.

`select_developing` is the pinned slot. Four gates, declared in
`app.stories.developing` and not tuned here: harm severity at least 0.6, at
least three independent tellers, at least one new member in twelve hours, and at
least a day old. Clearing all four is rare. That is the alert.

The reading page's feed is not rare. Clustering runs at :07 and :37, so the two
newest rows change up to 48 times a day, and alerting on them would be a
firehose. They are carried inside a pin's message as context and are never a
trigger, which costs nothing and holds a message at two or three titles.

## Announced once, and why that outlives a restart

A pinned story stays pinned for as long as it keeps gathering coverage, so
sending on every beat would re-send the same three every half hour. The
`notifications.dedup_key` UNIQUE index is what stops that, exactly as it stops
the watchdog re-paging a stale source.

The key carries no date, unlike the watchdog's. A source going quiet is worth
repeating each day it stays quiet; a story becoming developing happened once.
`app.housekeeping` does not prune `notifications`, so that holds for as long as
the database does — which is the point, and is why this needs no state file.

## Why it starts in dry run

How often a story pins has never been measured. Arming on the first deploy would
be guessing at how often a phone buzzes. With `DISCORD_ANNOUNCE_DRY_RUN` true —
the default — every read runs, the message is built, and it goes to the log
instead of to Discord.

A dry run still writes the notification row, exactly as an armed run does. A
mode that did not record would print the same three stories every half hour and
measure nothing, which is the one thing it exists to do. So turning it off does
not replay what the dry run saw. Those are not new.

    python -m app.stories.announce
    make announce
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import NotificationRow, StoryGistRow, StoryRow
from app.settings import settings
from app.stories.developing import DEFAULT_LIMIT, select_developing

logger = logging.getLogger(__name__)

#: The window the reading page reads over, and the pool it ranks inside. Both
#: mirror `osint-frontend/app/news/page.tsx`, so the two headlines in a message
#: are the two at the top of the page rather than a second answer to the same
#: question.
NEWS_WINDOW_HOURS: int = 48
NEWS_POOL: int = 60
#: How many headlines ride along. Two is a glance; the pin is what was sent.
NEWS_LINES: int = 2

#: Amber where the gist called the story escalating, otherwise the console's
#: cyan. Colour repeats a measurement rather than adding a judgement of its own.
COLOUR_ESCALATING: int = 0xE0A03C
COLOUR_NORMAL: int = 0x3BA9C4

#: Discord's own ceilings are 256 and 4096. Cut short of them, because a
#: headline ending exactly on the limit reads as a bug rather than as a headline.
TITLE_MAX: int = 220
GIST_MAX: int = 400


def _clip(text: str | None, limit: int) -> str:
    """One line, trimmed to fit. Collapses newlines too: a headline that wraps
    inside an embed field is a headline that has broken the layout."""
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres aware ones in the session's zone."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _age(moment: datetime | None, now: datetime) -> str:
    """How long ago, in the reading page's vocabulary. Unknown stays unknown."""
    moment = _as_utc(moment)
    if moment is None:
        return "—"
    minutes = int((now - moment).total_seconds() // 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 48 else f"{hours // 24}d ago"


def evidence_line(story: StoryRow, pin_reasons: dict[str, Any]) -> str:
    """The gates this story cleared, in the numbers that cleared them.

    The card justifies a pin rather than asserting it (#449), and a message that
    only asserted would be the weaker half of the same idea.
    """
    parts: list[str] = []
    severity = pin_reasons.get("max_severity")
    if isinstance(severity, (int, float)):
        parts.append(f"severity {float(severity):.2f}")
    parts.append(f"{story.owner_count} independent tellers")
    fresh = pin_reasons.get("new_members_12h")
    if isinstance(fresh, int):
        parts.append(f"{fresh} new in 12h")
    countries = pin_reasons.get("countries")
    if isinstance(countries, int) and countries:
        parts.append(f"{countries} countries" if countries > 1 else "1 country")
    age = pin_reasons.get("age_hours")
    if isinstance(age, int):
        parts.append(f"{age}h old" if age < 48 else f"{age // 24}d old")
    return " · ".join(parts)


def newest_headlines(
    session: Session, *, exclude: set[int], now: datetime, limit: int = NEWS_LINES
) -> list[StoryRow]:
    """The top of the reading page's News section, minus anything pinned.

    The page ranks the window's loudest `NEWS_POOL` stories and then shows them
    newest first, so this does the same two steps in the same order. Sorting the
    whole window by recency instead would be a different list that looked like
    this one — a story on one feed, minutes old, would displace what a reader
    actually sees at the top of the page.

    Pinned stories are excluded for the reason the page excludes them: a story
    repeated under its own alert reads as two stories.
    """
    cutoff = now - timedelta(hours=NEWS_WINDOW_HOURS)
    pool = (
        select(StoryRow.id)
        .where(StoryRow.last_seen >= cutoff)
        .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
        .limit(NEWS_POOL)
        .subquery()
    )
    stmt = (
        select(StoryRow)
        .where(StoryRow.id.in_(select(pool.c.id)))
        .order_by(StoryRow.last_seen.desc(), StoryRow.id.desc())
    )
    rows = session.execute(stmt).scalars().all()
    return [row for row in rows if row.id not in exclude][:limit]


def build_payload(
    pins: list[dict[str, Any]], headlines: list[StoryRow], now: datetime
) -> dict[str, Any]:
    """One Discord message: an embed per newly pinned story, then the context."""
    embeds: list[dict[str, Any]] = []
    for pin in pins:
        story: StoryRow = pin["story"]
        gist: StoryGistRow | None = pin["gist"]
        fields = [{"name": "Why it is pinned", "value": _clip(pin["evidence"], 400) or "—"}]
        if gist is not None and gist.category:
            fields.append({"name": "Tag", "value": _clip(gist.category, 60), "inline": True})
        embeds.append(
            {
                "title": _clip(story.title, TITLE_MAX) or "(untitled story)",
                "description": _clip(gist.gist if gist else None, GIST_MAX),
                "color": (
                    COLOUR_ESCALATING
                    if gist is not None and gist.escalating == "escalating"
                    else COLOUR_NORMAL
                ),
                "fields": fields,
            }
        )

    if headlines:
        lines = [f"`{_age(row.last_seen, now):>8}`  {_clip(row.title, 180)}" for row in headlines]
    else:
        lines = ["Nothing else in the window."]
    embeds.append(
        {
            "title": f"Also in the last {NEWS_WINDOW_HOURS}h",
            # Joined, not clipped: the lines are the point here, and the
            # whitespace-collapsing clip above would flatten them into one.
            "description": "\n".join(lines),
            "color": COLOUR_NORMAL,
        }
    )
    return {"username": "OSINT", "embeds": embeds}


def _discord_send(payload: dict[str, Any]) -> bool:
    """Best-effort push. Silent and successful when no webhook is configured.

    Returns False only when a configured webhook refused, so the caller can
    leave the story unannounced and try again on the next beat.
    """
    if not settings.discord_webhook_url:
        return True
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(settings.discord_webhook_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("announce: discord send failed: %s", exc)
        return False
    return True


def _persist_notification(session: Session, *, story_id: int, message: str) -> bool:
    """Insert one `notifications` row; True when this story is new.

    No date in the key, unlike the watchdog's. A source that is still quiet
    tomorrow is worth saying again; a story that became developing became
    developing once.
    """
    row = {
        "channel": "developing",
        "country": None,
        "score_value": None,
        "message": message,
        "dedup_key": f"developing:{story_id}",
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        insert = pg_insert
    elif dialect == "sqlite":
        insert = sqlite_insert
    else:
        raise NotImplementedError(f"announce does not support dialect {dialect!r}")
    stmt = (
        insert(NotificationRow)
        .values(row)
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(NotificationRow.id)
    )
    return session.execute(stmt).first() is not None


def _gists(session: Session, story_ids: list[int]) -> dict[int, StoryGistRow]:
    """Newest gist per story. A story with none is announced without one rather
    than held back: the pin is the finding, and the gist is a nicety the 1.5b
    brain may not have reached yet."""
    if not story_ids:
        return {}
    rows = session.execute(
        select(StoryGistRow)
        .where(StoryGistRow.story_id.in_(story_ids))
        .order_by(StoryGistRow.story_id, StoryGistRow.created_at.desc())
    ).scalars()
    newest: dict[int, StoryGistRow] = {}
    for row in rows:
        newest.setdefault(row.story_id, row)
    return newest


def announce_developing(
    session: Session, *, now: datetime | None = None, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """One sweep. Returns what was found, sent and skipped, for the job log."""
    now = now or datetime.now(UTC)
    dry_run = settings.discord_announce_dry_run or not settings.discord_webhook_url

    developing = select_developing(session, limit=limit, now=now)
    story_ids = [row["story_id"] for row in developing]
    report: dict[str, Any] = {
        "pinned": len(developing),
        "new": 0,
        "sent": False,
        "dry_run": dry_run,
    }
    if not developing:
        return report

    stories = {
        story.id: story
        for story in session.execute(select(StoryRow).where(StoryRow.id.in_(story_ids)))
        .scalars()
        .all()
    }
    gists = _gists(session, story_ids)

    pins: list[dict[str, Any]] = []
    for row in developing:
        story = stories.get(row["story_id"])
        if story is None:
            # Clustering can retire a story between the select and this read.
            continue
        evidence = evidence_line(story, row["pin_reasons"])
        if not _persist_notification(
            session, story_id=story.id, message=f"{story.title} — {evidence}"
        ):
            continue
        pins.append({"story": story, "gist": gists.get(story.id), "evidence": evidence})

    report["new"] = len(pins)
    if not pins:
        session.commit()
        logger.info("announce: %d pinned, none of them new", len(developing))
        return report

    payload = build_payload(pins, newest_headlines(session, exclude=set(story_ids), now=now), now)

    if dry_run:
        # Rolled back to nothing sent? No: the row is the record that this
        # story has been seen, and dry run is a measurement of arrival rate.
        # See the module docstring.
        session.commit()
        titles = " | ".join(_clip(pin["story"].title, 90) for pin in pins)
        logger.info("announce: DRY RUN — would have sent %d: %s", len(pins), titles)
        report["titles"] = [pin["story"].title for pin in pins]
        return report

    if not _discord_send(payload):
        # Not committed, so the next beat finds these stories new again rather
        # than dropping the one message that mattered.
        session.rollback()
        return report

    session.commit()
    report["sent"] = True
    logger.info("announce: sent %d newly developing stor(ies)", len(pins))
    return report


def main() -> int:
    """One-shot, for `make announce`. Prints what a beat would have done."""
    from sqlalchemy.orm import Session as _Session

    from app.db import get_engine

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with _Session(get_engine()) as session:
        report = announce_developing(session)
    mode = "dry run" if report["dry_run"] else "armed"
    print(
        f"{report['pinned']} pinned · {report['new']} new · "
        f"{'sent' if report['sent'] else 'nothing sent'} ({mode})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
