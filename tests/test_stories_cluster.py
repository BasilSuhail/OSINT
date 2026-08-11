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


def test_owner_count_collapses_same_owner_feeds() -> None:
    """WS-C step 2 (#355): three feeds but two owners → owner_count 2."""
    result = cluster_articles(
        [
            _article(1, "Wildfire forces mass evacuation in southern France", "rss-a"),
            _article(2, "Mass evacuation as wildfire spreads in southern France", "rss-b", 3),
            _article(3, "Southern France wildfire triggers mass evacuation", "rss-c", 7),
        ],
        existing=[],
        owner_map={"rss-a": "owner-1", "rss-b": "owner-1", "rss-c": "owner-2"},
    )
    (story,) = result.new_stories
    assert story["outlet_count"] == 3
    assert story["owner_count"] == 2


def test_sources_without_a_recorded_owner_do_not_count_as_independent() -> None:
    """Independence is recorded, never inferred from a missing record (#641).

    This test asserted the opposite until #641: unmapped slugs each counted as
    their own owner, so two unvetted feeds read as two independent tellers.
    `corroboration-v1.0` is exponential in `owner_count`, and #442 admits
    sources that arrive with no ownership record by definition — ten of them
    would have scored 0.998.
    """
    result = cluster_articles(
        [
            _article(1, "Wildfire forces mass evacuation in southern France", "rss-a"),
            _article(2, "Mass evacuation as wildfire spreads in southern France", "rss-b", 3),
        ],
        existing=[],
    )
    (story,) = result.new_stories
    assert story["outlet_count"] == 2
    assert story["owner_count"] == 0


def test_recorded_owners_still_count() -> None:
    result = cluster_articles(
        [
            _article(1, "Wildfire forces mass evacuation in southern France", "rss-a"),
            _article(2, "Mass evacuation as wildfire spreads in southern France", "rss-b", 3),
        ],
        existing=[],
        owner_map={"rss-a": "alpha-group", "rss-b": "beta-group"},
    )
    (story,) = result.new_stories
    assert story["owner_count"] == 2


def test_syndicated_feeds_still_collapse_to_one_owner() -> None:
    result = cluster_articles(
        [
            _article(1, "Wildfire forces mass evacuation in southern France", "rss-a"),
            _article(2, "Mass evacuation as wildfire spreads in southern France", "rss-b", 3),
        ],
        existing=[],
        owner_map={"rss-a": "reuters", "rss-b": "reuters"},
    )
    (story,) = result.new_stories
    assert story["outlet_count"] == 2
    assert story["owner_count"] == 1


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


# --------------------------------------------------------------------------- #
# Thin headlines (issue #890)                                                  #
# --------------------------------------------------------------------------- #


def test_a_one_word_headline_founds_nothing() -> None:
    # "Morning update" is a daily column's name, not a claim about the world.
    # `update` is boilerplate, so the headline reduces to a single token, and a
    # one-token centroid points at every article that happens to use the word.
    result = cluster_articles([_article(1, "Morning update")], existing=[])
    assert result.new_stories == []
    assert result.new_members == []


def test_a_column_name_does_not_join_a_real_story() -> None:
    result = cluster_articles(
        [
            _article(1, "Seoul stocks down late Tuesday morning on tech losses", "rss-yonhap"),
            _article(2, "Morning update", "rss-mee", minutes=30),
        ],
        existing=[],
    )
    assert {m["event_id"] for m in result.new_members} == {1}, (
        "a newsletter's name was read as a second outlet telling the market story"
    )
    (story,) = result.new_stories
    assert story["outlet_count"] == 1


def test_a_thin_headline_already_in_a_story_stops_pulling_others_in() -> None:
    # The centroid is rebuilt from member titles every run. A one-token member
    # left in that rebuild keeps the story pointed at its single word, which is
    # how one newsletter's name kept collecting the next day's edition.
    existing = [{"event_id": 1, "story_id": 7, "title": "Morning update"}]
    result = cluster_articles(
        [_article(2, "Morning recap", "rss-mee", minutes=60)],
        existing=existing,
    )
    assert result.new_members == []


def test_one_shared_word_is_not_a_shared_story() -> None:
    # Both headlines are substantial and both are about Iran; they are not
    # about the same event, and a single overlapping token cannot tell them
    # apart from a paraphrase.
    result = cluster_articles(
        [
            _article(1, "Iran warns it will not be pressured into fresh nuclear talks"),
            _article(2, "Trump sends Congress formal notice on strikes", minutes=5),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 2


def test_two_shared_words_still_cluster() -> None:
    result = cluster_articles(
        [
            _article(1, "Powerful earthquake strikes Tokyo, dozens injured", "rss-a"),
            _article(2, "Tokyo earthquake leaves dozens injured", "rss-b", minutes=5),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 1
    assert {m["event_id"] for m in result.new_members} == {1, 2}


def _member(event_id: int, story_id: int, title: str) -> dict:
    return {"event_id": event_id, "story_id": story_id, "title": title}


def test_two_disasters_in_different_countries_are_two_stories() -> None:
    # The casualty formula is a headline shape, not a subject: "death toll
    # rises to N" says the same words about every disaster on earth. Two
    # quakes a hemisphere apart share every token but the place name, and the
    # place name is the whole of the difference.
    result = cluster_articles(
        [
            _article(1, "Death toll from Japan earthquake rises to 14 as search continues"),
            _article(
                2, "Death toll from Colombia earthquake rises to 14 as search goes on", minutes=5
            ),
        ],
        existing=[],
    )
    assert len(result.new_stories) == 2


def test_a_story_anchored_on_one_country_refuses_another() -> None:
    # A running story about Japan does not get to collect Gaza, however alike
    # the two headlines read.
    existing = [
        _member(1, 42, "Death toll from Japan earthquake rises to 14 as search continues"),
        _member(2, 42, "Japan earthquake death toll rises to 30 as rescuers search rubble"),
        _member(3, 42, "Death toll from earthquake in Japan rises to 34, rescuers continue"),
    ]
    result = cluster_articles(
        [
            _article(
                4, "Death toll from Gaza strike rises to 34 as rescuers search rubble", minutes=30
            )
        ],
        existing=existing,
    )
    assert all(m["story_id"] != 42 for m in result.new_members)


def test_a_story_keeps_a_country_it_already_tells() -> None:
    # A story genuinely about two countries must go on accepting both — the
    # gate refuses a contradiction, never a continuation.
    existing = [
        _member(1, 7, "Spain beat Argentina to reach the World Cup final in Dallas"),
        _member(2, 7, "Argentina and Spain prepare for the World Cup final"),
        _member(3, 7, "World Cup final: Spain face Argentina"),
    ]
    result = cluster_articles(
        [_article(4, "Spain beat Argentina 1-0 to win the World Cup final", minutes=30)],
        existing=existing,
    )
    (member,) = result.new_members
    assert member["story_id"] == 7


def test_a_headline_naming_nowhere_is_not_blocked() -> None:
    # Absence is not a contradiction. Most headlines name no country at all,
    # and a gate that treated silence as a conflict would refuse the corpus.
    existing = [
        _member(1, 9, "Death toll from Japan earthquake rises to 14 as search continues"),
        _member(2, 9, "Japan earthquake death toll rises to 30 as rescuers search rubble"),
    ]
    result = cluster_articles(
        [_article(3, "Death toll rises to 30 as rescuers search rubble after quake", minutes=30)],
        existing=existing,
    )
    (member,) = result.new_members
    assert member["story_id"] == 9


def test_a_story_naming_nowhere_blocks_nothing() -> None:
    existing = [
        _member(1, 11, "Central bank raises interest rates amid inflation fears"),
        _member(2, 11, "Interest rates raised again as inflation fears persist"),
    ]
    result = cluster_articles(
        [_article(3, "Japan raises interest rates amid inflation fears", minutes=30)],
        existing=existing,
    )
    (member,) = result.new_members
    assert member["story_id"] == 11
