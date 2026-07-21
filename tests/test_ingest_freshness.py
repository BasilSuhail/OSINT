"""Rejecting events that are not current at ingest (#571)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ingest import freshness
from app.models import Category, Event


def _event(source: str, occurred_at: datetime, title: str = "t") -> Event:
    return Event(
        source=source,
        source_event_id=f"{source}-{occurred_at.isoformat()}-{title}",
        occurred_at=occurred_at,
        fetched_at=datetime.now(UTC),
        category=Category.GEOPOLITICAL,
        severity=None,
        confidence=None,
        keywords=[],
        country="JP",
        lat=None,
        lon=None,
        payload={"title": title},
    )


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class TestMaxAge:
    def test_news_is_bounded_by_the_retention_window(self) -> None:
        # The rule is "do not ingest what retention would immediately delete",
        # which is defensible where an arbitrary number is not.
        assert freshness.max_age("rss-bbc-world") == freshness.RETENTION_ALIGNED_MAX_AGE

    def test_market_and_macro_are_unbounded(self) -> None:
        # FRED history runs to 385 days at ingest and yfinance to 7 — historical
        # depth is the entire point of these sources.
        for source in ("fred", "yfinance", "emdat", "acled", "uk-police"):
            assert freshness.max_age(source) is None, source

    def test_cyber_feeds_get_headroom_above_their_published_window(self) -> None:
        # urlhaus publishes a rolling window: measured p99 30.3 days at ingest.
        bound = freshness.max_age("abuse-ch-urlhaus")
        assert bound is not None and bound > timedelta(days=31)

    def test_an_unknown_source_gets_the_default_rather_than_a_free_pass(self) -> None:
        assert freshness.max_age("something-new") == freshness.RETENTION_ALIGNED_MAX_AGE


class TestPartition:
    def test_a_current_event_is_kept(self) -> None:
        kept, rejected = freshness.partition(
            [_event("rss-bbc-world", NOW - timedelta(hours=3))], now=NOW
        )
        assert len(kept) == 1 and rejected == []

    def test_an_ancient_event_is_rejected(self) -> None:
        # The CNN case: "Donate now to a Top 10 CNN Hero", dated 2021.
        old = _event("rss-cnn-world", NOW - timedelta(days=1200), "Donate now to a CNN Hero")
        kept, rejected = freshness.partition([old], now=NOW)
        assert kept == []
        assert len(rejected) == 1
        assert "1200" in rejected[0].reason or "days" in rejected[0].reason

    def test_a_healthy_feed_keeps_its_recent_items_and_loses_only_the_tail(self) -> None:
        # daily-sabah: p50 lag 0.62 days, with a tail out to 2,340. The feed
        # must survive; only the tail goes.
        events = [
            _event("rss-daily-sabah", NOW - timedelta(hours=6), "fresh"),
            _event("rss-daily-sabah", NOW - timedelta(days=2340), "ancient"),
        ]
        kept, rejected = freshness.partition(events, now=NOW)
        assert [e.payload["title"] for e in kept] == ["fresh"]
        assert [r.event.payload["title"] for r in rejected] == ["ancient"]

    def test_slow_publishing_outlets_are_not_punished(self) -> None:
        # jpost p99 19.3 days, responsible-statecraft 12.0, guardian 9.6 — all
        # legitimate. A naive 7-day rule would have deleted these.
        for source, age_days in (
            ("rss-jpost-world", 19),
            ("rss-responsible-statecraft", 12),
            ("rss-guardian-world", 10),
        ):
            kept, rejected = freshness.partition(
                [_event(source, NOW - timedelta(days=age_days))], now=NOW
            )
            assert len(kept) == 1, f"{source} at {age_days}d was wrongly rejected"
            assert rejected == []

    def test_macro_history_is_never_rejected(self) -> None:
        kept, rejected = freshness.partition([_event("fred", NOW - timedelta(days=385))], now=NOW)
        assert len(kept) == 1 and rejected == []

    def test_a_future_dated_event_is_rejected(self) -> None:
        kept, rejected = freshness.partition(
            [_event("rss-jpost-world", NOW + timedelta(hours=12))], now=NOW
        )
        assert kept == []
        assert "future" in rejected[0].reason.lower()

    def test_small_clock_skew_is_tolerated(self) -> None:
        # Feeds disagree with us by minutes routinely; that is not a defect.
        kept, _ = freshness.partition(
            [_event("rss-bbc-world", NOW + timedelta(minutes=20))], now=NOW
        )
        assert len(kept) == 1

    def test_an_event_with_no_date_is_kept_rather_than_guessed_about(self) -> None:
        # Dropping on a missing field would silently lose real news; that is a
        # parser problem, not a freshness one.
        event = _event("rss-bbc-world", NOW - timedelta(hours=1))
        event.occurred_at = None
        kept, rejected = freshness.partition([event], now=NOW)
        assert len(kept) == 1 and rejected == []

    def test_naive_datetimes_are_handled(self) -> None:
        # A fetcher that forgets tzinfo must not crash the guard.
        event = _event("rss-bbc-world", NOW - timedelta(hours=2))
        event.occurred_at = event.occurred_at.replace(tzinfo=None)
        kept, rejected = freshness.partition([event], now=NOW)
        assert len(kept) == 1 and rejected == []


class TestSummary:
    def test_the_summary_names_the_worst_offender(self) -> None:
        rejected = freshness.partition(
            [
                _event("rss-cnn-world", NOW - timedelta(days=1200), "promo"),
                _event("rss-cnn-world", NOW - timedelta(days=900), "old"),
            ],
            now=NOW,
        )[1]
        summary = freshness.summarize(rejected)
        assert "2" in summary
        assert "promo" in summary or "1200" in summary

    def test_no_rejections_summarizes_to_nothing(self) -> None:
        assert freshness.summarize([]) is None
