"""Tests for `app.disagreement.tellings` — per-country telling divergence."""

from __future__ import annotations

from app.disagreement.tellings import METHOD_VERSION, story_divergence


def _member(title: str, source: str) -> dict:
    return {"title": title, "source": source}


COUNTRY_MAP = {"rss-a": "GB", "rss-b": "GB", "rss-c": "RU", "rss-d": "FR"}


def test_identical_tellings_diverge_near_zero() -> None:
    result = story_divergence(
        [
            _member("Earthquake strikes Tokyo overnight", "rss-a"),
            _member("Earthquake strikes Tokyo overnight", "rss-c"),
        ],
        country_map=COUNTRY_MAP,
    )
    assert result is not None
    # Identical centroids give cosine 1.0 ± float epsilon — never below zero.
    assert 0.0 <= result["divergence"] < 0.01
    assert result["components"]["groups"] == {"GB": 1, "RU": 1}


def test_different_angles_diverge_more() -> None:
    same = story_divergence(
        [
            _member("Ceasefire announced in overnight talks", "rss-a"),
            _member("Ceasefire announced after overnight talks", "rss-c"),
        ],
        country_map=COUNTRY_MAP,
    )
    framed = story_divergence(
        [
            _member("Ceasefire announced in overnight talks", "rss-a"),
            _member("Aggressors forced into humiliating retreat, ceasefire imposed", "rss-c"),
        ],
        country_map=COUNTRY_MAP,
    )
    assert same is not None and framed is not None
    assert framed["divergence"] > same["divergence"]


def test_single_country_story_has_no_divergence() -> None:
    result = story_divergence(
        [
            _member("Local election results announced", "rss-a"),
            _member("Election results are in", "rss-b"),  # both GB
        ],
        country_map=COUNTRY_MAP,
    )
    assert result is None


def test_unknown_source_excluded_from_groups() -> None:
    result = story_divergence(
        [
            _member("Earthquake strikes Tokyo overnight", "rss-a"),
            _member("Earthquake strikes Tokyo overnight", "rss-unknown"),
        ],
        country_map=COUNTRY_MAP,
    )
    assert result is None  # only one *known-origin* group remains


def test_three_groups_average_all_pairs() -> None:
    result = story_divergence(
        [
            _member("Summit ends with new trade agreement", "rss-a"),
            _member("Summit ends with new trade agreement", "rss-c"),
            _member("Summit collapses without any agreement signed", "rss-d"),
        ],
        country_map=COUNTRY_MAP,
    )
    assert result is not None
    assert result["components"]["n_pairs"] == 3
    assert 0.0 <= result["divergence"] <= 1.0
    assert result["components"]["method_version"] == METHOD_VERSION == "disagreement-v1.0"


def test_components_carry_per_pair_distances() -> None:
    """WS-B step 3 (#372): the roll-up needs each pair's own distance."""
    result = story_divergence(
        [
            _member("Summit ends with new trade agreement", "rss-a"),
            _member("Summit ends with new trade agreement", "rss-c"),
            _member("Summit collapses without any agreement signed", "rss-d"),
        ],
        country_map=COUNTRY_MAP,
    )
    assert result is not None
    pairs = result["components"]["pairs"]
    assert set(pairs) == {"FR|GB", "FR|RU", "GB|RU"}
    assert pairs["GB|RU"] < 0.01  # identical wording
    assert pairs["FR|GB"] > pairs["GB|RU"]  # different angle
    for value in pairs.values():
        assert 0.0 <= value <= 1.0
    # Story divergence is exactly the mean of the pair values.
    assert abs(result["divergence"] - sum(pairs.values()) / 3) < 1e-9
