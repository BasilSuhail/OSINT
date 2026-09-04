"""Tests for `app.stories.announce` — developing stories into Discord (#1039)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, NotificationRow, StoryGistRow, StoryMemberRow, StoryRow
from app.stories import announce as mod
from app.stories.announce import (
    NEWS_WINDOW_HOURS,
    announce_developing,
    build_payload,
    evidence_line,
    newest_headlines,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Seeding — same shape as tests/test_stories_developing.py, so a story that
# qualifies here qualifies there for the same declared reasons.
# --------------------------------------------------------------------------
def _story(
    session: Session,
    *,
    title: str,
    age_hours: int = 48,
    last_seen_hours: int = 1,
    outlet_count: int = 5,
    owner_count: int | None = None,
) -> int:
    story = StoryRow(
        title=title,
        first_seen=NOW - timedelta(hours=age_hours),
        last_seen=NOW - timedelta(hours=last_seen_hours),
        member_count=outlet_count,
        outlet_count=outlet_count,
        owner_count=outlet_count if owner_count is None else owner_count,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    return story.id


def _member(
    session: Session, story_id: int, *, severity: float, country: str, added_hours: int = 2
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


def _pinnable(session: Session, title: str = "border crossing closed", **kw) -> int:
    """A story clearing all four gates: severity, owners, velocity, age."""
    story_id = _story(session, title=title, owner_count=4, **kw)
    for country in ("UA", "PL", "RO"):
        _member(session, story_id, severity=0.75, country=country)
    session.commit()
    return story_id


def _gist(session: Session, story_id: int, *, escalating: str = "steady") -> None:
    session.add(
        StoryGistRow(
            story_id=story_id,
            gist="Third night of strikes on the corridor.",
            category="conflict",
            escalating=escalating,
            model="qwen",
            method_version="gist-v1.0",
            created_at=NOW,
        )
    )
    session.commit()


@pytest.fixture
def armed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Configure a webhook, arm it, and capture what would be posted."""
    posts: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, **_: Any) -> None:
            pass

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
            posts.append({"url": url, "json": json})
            return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(mod.settings, "discord_webhook_url", "https://example.invalid/hook")
    monkeypatch.setattr(mod.settings, "discord_announce_dry_run", False)
    monkeypatch.setattr(mod.httpx, "Client", _FakeClient)
    return posts


class TestAnnounce:
    def test_a_newly_pinned_story_is_sent_once(
        self, db_session: Session, armed: list[dict[str, Any]]
    ) -> None:
        story_id = _pinnable(db_session)
        _gist(db_session, story_id, escalating="escalating")

        report = announce_developing(db_session, now=NOW)
        assert report["new"] == 1
        assert report["sent"] is True
        assert len(armed) == 1

        embeds = armed[0]["json"]["embeds"]
        assert embeds[0]["title"] == "border crossing closed"
        assert embeds[0]["description"].startswith("Third night")
        assert embeds[0]["color"] == mod.COLOUR_ESCALATING

    def test_the_same_story_is_not_sent_again(
        self, db_session: Session, armed: list[dict[str, Any]]
    ) -> None:
        _pinnable(db_session)
        announce_developing(db_session, now=NOW)
        armed.clear()

        report = announce_developing(db_session, now=NOW + timedelta(minutes=30))
        assert report["pinned"] == 1
        assert report["new"] == 0
        assert report["sent"] is False
        assert armed == []

    def test_a_story_with_no_gist_is_still_announced(
        self, db_session: Session, armed: list[dict[str, Any]]
    ) -> None:
        _pinnable(db_session)
        report = announce_developing(db_session, now=NOW)
        assert report["new"] == 1
        assert armed[0]["json"]["embeds"][0]["description"] == ""

    def test_nothing_pinned_sends_nothing(
        self, db_session: Session, armed: list[dict[str, Any]]
    ) -> None:
        # Fresh, loud, but hours old: fails the multi-day gate.
        story_id = _story(db_session, title="flash", age_hours=2, owner_count=4)
        _member(db_session, story_id, severity=0.9, country="FR")
        db_session.commit()

        report = announce_developing(db_session, now=NOW)
        assert report == {"pinned": 0, "new": 0, "sent": False, "dry_run": False}
        assert armed == []

    def test_a_refused_post_leaves_the_story_unannounced(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pinnable(db_session)
        monkeypatch.setattr(mod.settings, "discord_webhook_url", "https://example.invalid/hook")
        monkeypatch.setattr(mod.settings, "discord_announce_dry_run", False)
        monkeypatch.setattr(mod, "_discord_send", lambda payload: False)

        report = announce_developing(db_session, now=NOW)
        assert report["new"] == 1
        assert report["sent"] is False
        # Nothing recorded, so the next beat finds it new again rather than
        # dropping the one message that mattered.
        assert db_session.execute(select(NotificationRow)).first() is None

    def test_the_retry_after_a_refusal_delivers_it(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch, armed: list[dict[str, Any]]
    ) -> None:
        _pinnable(db_session)
        # Refuses once, then behaves. `monkeypatch.undo()` cannot be used to
        # flip it back: the fixture above shares this same monkeypatch, so
        # undoing would also un-arm the sender under test.
        real_send = mod._discord_send
        calls = {"n": 0}

        def flaky(payload: dict[str, Any]) -> bool:
            calls["n"] += 1
            return real_send(payload) if calls["n"] > 1 else False

        monkeypatch.setattr(mod, "_discord_send", flaky)

        assert announce_developing(db_session, now=NOW)["sent"] is False
        report = announce_developing(db_session, now=NOW + timedelta(minutes=30))
        assert report["sent"] is True
        assert len(armed) == 1


class TestDryRun:
    def test_dry_run_posts_nothing(
        self, db_session: Session, armed: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod.settings, "discord_announce_dry_run", True)
        _pinnable(db_session)

        report = announce_developing(db_session, now=NOW)
        assert report["dry_run"] is True
        assert report["new"] == 1
        assert report["sent"] is False
        assert armed == []
        assert report["titles"] == ["border crossing closed"]

    def test_dry_run_still_records_what_it_saw(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measurement is the arrival rate, so a dry run that did not record
        would print the same story every beat and measure nothing."""
        monkeypatch.setattr(mod.settings, "discord_announce_dry_run", True)
        story_id = _pinnable(db_session)
        announce_developing(db_session, now=NOW)

        row = db_session.execute(select(NotificationRow)).scalar_one()
        assert row.dedup_key == f"developing:{story_id}"
        assert row.channel == "developing"
        assert announce_developing(db_session, now=NOW)["new"] == 0

    def test_a_missing_webhook_forces_dry_run(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod.settings, "discord_webhook_url", "")
        monkeypatch.setattr(mod.settings, "discord_announce_dry_run", False)
        _pinnable(db_session)
        assert announce_developing(db_session, now=NOW)["dry_run"] is True


class TestHeadlines:
    def test_pinned_stories_are_not_repeated_below(self, db_session: Session) -> None:
        pinned = _pinnable(db_session)
        _story(db_session, title="a second story", last_seen_hours=2)
        db_session.commit()

        rows = newest_headlines(db_session, exclude={pinned}, now=NOW)
        assert [row.title for row in rows] == ["a second story"]

    def test_newest_first_and_capped_at_two(self, db_session: Session) -> None:
        _story(db_session, title="oldest", last_seen_hours=9)
        _story(db_session, title="newest", last_seen_hours=1)
        _story(db_session, title="middle", last_seen_hours=3)
        db_session.commit()

        rows = newest_headlines(db_session, exclude=set(), now=NOW)
        assert [row.title for row in rows] == ["newest", "middle"]

    def test_stories_outside_the_window_are_not_shown(self, db_session: Session) -> None:
        _story(db_session, title="stale", last_seen_hours=NEWS_WINDOW_HOURS + 1)
        db_session.commit()
        assert newest_headlines(db_session, exclude=set(), now=NOW) == []

    def test_an_empty_window_is_said_out_loud(self, db_session: Session) -> None:
        payload = build_payload([], [], NOW)
        assert payload["embeds"][-1]["description"] == "Nothing else in the window."


class TestPayload:
    def test_the_two_headlines_stay_on_separate_lines(self, db_session: Session) -> None:
        """Regression: collapsing whitespace to keep a headline on one line also
        flattened the whole context block into a single run-on paragraph."""
        _story(db_session, title="first headline", last_seen_hours=1)
        _story(db_session, title="second headline", last_seen_hours=3)
        db_session.commit()

        payload = build_payload([], newest_headlines(db_session, exclude=set(), now=NOW), NOW)
        description = payload["embeds"][-1]["description"]
        assert description.count("\n") == 1
        assert description.index("first headline") < description.index("second headline")
        assert "1h ago" in description and "3h ago" in description

    def test_evidence_names_the_gates_that_were_cleared(self, db_session: Session) -> None:
        story_id = _pinnable(db_session)
        story = db_session.get(StoryRow, story_id)
        line = evidence_line(
            story,
            {"max_severity": 0.75, "countries": 3, "new_members_12h": 2, "age_hours": 48},
        )
        assert line == "severity 0.75 · 4 independent tellers · 2 new in 12h · 3 countries · 2d old"

    def test_a_long_headline_is_cut_short_of_discord_s_limit(self, db_session: Session) -> None:
        _story(db_session, title="x" * 500, last_seen_hours=1)
        db_session.commit()
        payload = build_payload([], newest_headlines(db_session, exclude=set(), now=NOW), NOW)
        assert "…" in payload["embeds"][-1]["description"]
