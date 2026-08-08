"""Sizing the Reddit tier before building it (#804).

Every test here is offline. The probe's only network call is one thin
function, and the rules worth testing — what counts as a link post, what
counts as the same story, what happens on a 429 — are pure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.audit import reddit_probe
from app.db_models import Base, EventRow

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        yield s


def _feed(*entries: str) -> str:
    body = "".join(entries)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


def _entry(title: str, *, stamp: str, post_id: str = "t3_abc", content: str = "") -> str:
    return (
        f"<entry><id>{post_id}</id><title>{title}</title>"
        f"<updated>{stamp}</updated><content>{content}</content></entry>"
    )


SELF_POST_CONTENT = '&lt;a href="https://www.reddit.com/r/Edinburgh/comments/abc"&gt;link&lt;/a&gt;'


class TestParsing:
    def test_entries_become_posts(self) -> None:
        xml = _feed(_entry("Explosion sound??", stamp="2026-08-08T11:00:00+00:00"))
        posts = reddit_probe.parse_feed(xml, subreddit="Edinburgh")
        assert len(posts) == 1
        assert posts[0].title == "Explosion sound??"
        assert posts[0].posted_at == datetime(2026, 8, 8, 11, 0, tzinfo=UTC)

    def test_an_entry_without_a_timestamp_is_skipped(self) -> None:
        xml = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        xml += "<entry><id>x</id><title>No date</title></entry></feed>"
        assert reddit_probe.parse_feed(xml, subreddit="Edinburgh") == []

    def test_posting_rate_comes_from_the_span_of_the_entries(self) -> None:
        """The volume question #804 calls unmeasurable: the feed returns the
        25 newest whatever the window, but each carries its own timestamp."""
        xml = _feed(
            _entry("a", stamp="2026-08-08T12:00:00+00:00", post_id="1"),
            _entry("b", stamp="2026-08-08T00:00:00+00:00", post_id="2"),
            _entry("c", stamp="2026-08-07T12:00:00+00:00", post_id="3"),
        )
        result = reddit_probe.SubredditProbe(
            subreddit="Edinburgh", posts=reddit_probe.parse_feed(xml, subreddit="Edinburgh")
        )
        assert result.span_hours == 24.0
        assert result.posts_per_day == 2.0


class TestLinkPosts:
    def test_a_link_to_a_newsroom_is_a_repost(self) -> None:
        """The strongest Edinburgh post in the first pass was a link to a
        local title — tier-one content without its owner attached."""
        content = '&lt;a href="https://www.edinburghlive.co.uk/news/three-charged"&gt;x&lt;/a&gt;'
        xml = _feed(_entry("Three charged", stamp="2026-08-08T11:00:00+00:00", content=content))
        post = reddit_probe.parse_feed(xml, subreddit="Edinburgh")[0]
        assert post.is_link_post
        assert post.external_url == "https://www.edinburghlive.co.uk/news/three-charged"

    def test_a_self_post_links_only_back_to_reddit(self) -> None:
        entry = _entry(
            "Explosion sound??", stamp="2026-08-08T11:00:00+00:00", content=SELF_POST_CONTENT
        )
        xml = _feed(entry)
        post = reddit_probe.parse_feed(xml, subreddit="Edinburgh")[0]
        assert not post.is_link_post
        assert post.external_url is None


class TestMatching:
    def _post(self, title: str, *, minutes: int = 0) -> reddit_probe.RedditPost:
        return reddit_probe.RedditPost(
            subreddit="Edinburgh",
            post_id=f"t3_{abs(minutes)}",
            title=title,
            posted_at=NOW + timedelta(minutes=minutes),
            external_url=None,
        )

    def _row(self, title: str, *, minutes: int) -> EventRow:
        return EventRow(
            source="rss-edinburgh-live",
            source_event_id=f"row-{minutes}",
            occurred_at=NOW + timedelta(minutes=minutes),
            category="geopolitical",
            keywords=[],
            payload={"title": title},
        )

    def test_reddit_first_reports_a_negative_lead(self, session) -> None:
        headline = "Police make 49 arrests in Edinburgh city centre crackdown"
        session.add(self._row(headline, minutes=40))
        session.commit()
        matches = reddit_probe.match_to_events(session, [self._post(headline)])
        assert len(matches) == 1
        assert matches[0].lead_minutes == -40

    def test_the_wire_first_reports_a_positive_lead(self, session) -> None:
        session.add(self._row("Police make 49 arrests in Edinburgh city centre", minutes=-25))
        session.commit()
        matches = reddit_probe.match_to_events(
            session, [self._post("Police make 49 arrests in Edinburgh city centre")]
        )
        assert matches[0].lead_minutes == 25

    def test_an_unrelated_headline_is_not_a_match(self, session) -> None:
        session.add(self._row("Edinburgh tram extension opens to passengers", minutes=10))
        session.commit()
        assert reddit_probe.match_to_events(session, [self._post("Explosion sound??")]) == []

    def test_a_story_days_away_is_a_different_telling(self, session) -> None:
        session.add(self._row("Police make 49 arrests in Edinburgh city centre", minutes=-5000))
        session.commit()
        assert (
            reddit_probe.match_to_events(
                session, [self._post("Police make 49 arrests in Edinburgh city centre")]
            )
            == []
        )

    def test_untitled_rows_cannot_be_twins(self, session) -> None:
        row = self._row("ignored", minutes=5)
        row.payload = {}
        session.add(row)
        session.commit()
        assert reddit_probe.match_to_events(session, [self._post("Explosion sound??")]) == []

    def test_the_median_lead_is_reported_over_several_matches(self, session) -> None:
        session.add_all(
            [
                self._row("Fire breaks out at Leith warehouse", minutes=30),
                self._row("Tram services suspended after Princes Street fault", minutes=90),
            ]
        )
        session.commit()
        posts = [
            self._post("Fire breaks out at Leith warehouse", minutes=0),
            self._post("Tram services suspended after Princes Street fault", minutes=10),
        ]
        result = reddit_probe.SubredditProbe(
            subreddit="Edinburgh",
            posts=posts,
            matches=reddit_probe.match_to_events(session, posts),
        )
        assert result.median_lead_minutes == -55.0


class TestPacing:
    def _client(self, responses: list[httpx.Response]) -> httpx.Client:
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            return queue.pop(0)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_a_429_is_retried_after_backing_off(self) -> None:
        slept: list[float] = []
        client = self._client(
            [httpx.Response(429), httpx.Response(200, text=_feed())],
        )
        body, status = reddit_probe.fetch_feed("Edinburgh", client=client, sleep=slept.append)
        assert status == 200
        assert body is not None
        assert slept, "a 429 was retried immediately"

    def test_the_hosts_own_retry_after_wins(self) -> None:
        slept: list[float] = []
        client = self._client(
            [httpx.Response(429, headers={"retry-after": "9"}), httpx.Response(200, text=_feed())]
        )
        reddit_probe.fetch_feed("Edinburgh", client=client, sleep=slept.append)
        assert slept == [9.0]

    def test_it_gives_up_rather_than_hammering(self) -> None:
        slept: list[float] = []
        client = self._client([httpx.Response(429) for _ in range(reddit_probe.MAX_ATTEMPTS)])
        body, status = reddit_probe.fetch_feed("Edinburgh", client=client, sleep=slept.append)
        assert body is None
        assert status == 429
        assert len(slept) == reddit_probe.MAX_ATTEMPTS - 1

    def test_a_404_is_not_retried(self) -> None:
        slept: list[float] = []
        client = self._client([httpx.Response(404)])
        body, status = reddit_probe.fetch_feed("Edinburgh", client=client, sleep=slept.append)
        assert (body, status, slept) == (None, 404, [])


class TestProbeRun:
    def test_requests_are_spaced_and_failures_are_reported(self, session) -> None:
        slept: list[float] = []
        pages = [httpx.Response(200, text=_feed()), httpx.Response(403)]

        def handler(request: httpx.Request) -> httpx.Response:
            return pages.pop(0)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        results = reddit_probe.probe(
            session, subreddits=("Edinburgh", "Cairo"), client=client, sleep=slept.append
        )
        assert [r.subreddit for r in results] == ["Edinburgh", "Cairo"]
        assert results[1].failed_with == 403
        assert reddit_probe.REQUEST_SPACING_SECONDS in slept

    def test_nothing_is_written_to_events(self, session) -> None:
        """The whole point: this measures a source without becoming one."""
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, text=_feed(_entry("Explosion sound??", stamp="2026-08-08T11:00:00+00:00"))
                )
            )
        )
        reddit_probe.probe(session, subreddits=("Edinburgh",), client=client, sleep=lambda _s: None)
        assert session.query(EventRow).count() == 0
