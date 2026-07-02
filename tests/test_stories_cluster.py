"""Tests for `app.stories.cluster` — greedy leader clustering of headlines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.stories.cluster import cluster_articles

T0 = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


def _article(event_id: int, title: str, source: str = "rss-a", minutes: int = 0) -> dict:
    return {
        "event_id": event_id,
        "title": title,
        "source": source,
        "occurred_at": T0 + timedelta(minutes=minutes),
    }


def test_paraphrase_headlines_cluster() -> None:
    result = cluster_articles(
        [
            _article(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"),
            _article(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", minutes=5),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 1
    assert {m["event_id"] for m in result.new_members} == {1, 2}


def test_unrelated_headlines_do_not_cluster() -> None:
    result = cluster_articles(
        [
            _article(1, "Powerful earthquake strikes Tokyo, dozens injured"),
            _article(2, "Central bank raises interest rates amid inflation fears", minutes=5),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 2


def test_three_outlets_one_story() -> None:
    result = cluster_articles(
        [
            _article(1, "Wildfire forces mass evacuation in southern France", "rss-a"),
            _article(2, "Mass evacuation as wildfire spreads in southern France", "rss-b", 3),
            _article(3, "Southern France wildfire triggers mass evacuation", "rss-c", 7),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 1
    (story,) = result.new_stories
    assert story["outlet_count"] == 3
    assert story["member_count"] == 3
    assert story["title"] == "Wildfire forces mass evacuation in southern France"


def test_incremental_run_joins_existing_story() -> None:
    first = cluster_articles(
        [
            _article(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"),
            _article(2, "Dozens injured as powerful earthquake hits Tokyo", "rss-b", 5),
        ],
        existing=[],
    )
    (story,) = first.new_stories
    existing = [
        {
            "event_id": m["event_id"],
            "story_id": 42,
            "title": a["title"],
        }
        for m, a in zip(
            first.new_members,
            [
                _article(1, "Powerful earthquake strikes Tokyo, dozens injured"),
                _article(2, "Dozens injured as powerful earthquake hits Tokyo"),
            ],
            strict=True,
        )
    ]
    second = cluster_articles(
        [_article(3, "Tokyo earthquake: injured toll rises to dozens", "rss-c", 30)],
        existing=existing,
    )
    assert second.new_stories == []
    (member,) = second.new_members
    assert member["story_id"] == 42
    assert story is not None  # first pass produced the story


def test_existing_assignments_never_touched() -> None:
    existing = [{"event_id": 1, "story_id": 7, "title": "Old headline about something"}]
    result = cluster_articles(
        [_article(2, "Completely unrelated fresh headline on markets", minutes=10)],
        existing=existing,
    )
    assert all(m["event_id"] != 1 for m in result.new_members)


def test_empty_input_noop() -> None:
    result = cluster_articles([], existing=[])
    assert result.new_stories == []
    assert result.new_members == []


def test_untitled_articles_skipped() -> None:
    result = cluster_articles([_article(1, "")], existing=[])
    assert result.new_stories == []
