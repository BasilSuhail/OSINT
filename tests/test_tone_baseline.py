"""Measuring the bloc tone signal (#639).

The arithmetic is tested here so the reported numbers cannot be wrong in a way
nobody notices — the whole point of #639 is that a number nobody checked has
been shipping for months.
"""

from __future__ import annotations

from app.enrichment import tone_llm
from app.enrichment.tone_baseline import (
    Member,
    dominant_label,
    measure_agreement,
    measure_discrimination,
)


def _member(story_id: int, country: str, label: str | None) -> Member:
    return Member(story_id=story_id, origin_country=country, label=label)


class TestDominantLabel:
    def test_picks_the_majority(self) -> None:
        assert dominant_label(["negative", "negative", "neutral"]) == "negative"

    def test_a_tie_is_no_lean_rather_than_a_coin_flip(self) -> None:
        # Breaking a 1-1 split would manufacture exactly the disagreement the
        # measurement is trying to count.
        assert dominant_label(["negative", "positive"]) is None

    def test_ignores_labels_outside_the_rubric(self) -> None:
        assert dominant_label(["negative", "bananas", "negative"]) == "negative"

    def test_no_usable_labels_is_none(self) -> None:
        assert dominant_label([]) is None
        assert dominant_label(["bananas"]) is None


class TestMeasureDiscrimination:
    def test_counts_a_story_where_blocs_disagree(self) -> None:
        members = [
            _member(1, "RU", "negative"),
            _member(1, "RU", "negative"),
            _member(1, "US", "positive"),
            _member(1, "US", "positive"),
        ]
        report = measure_discrimination(members)
        assert report.stories_considered == 1
        assert report.stories_unanimous == 0
        assert report.unanimous_share == 0.0

    def test_counts_a_story_where_blocs_agree(self) -> None:
        # The case that would make the feature decorative: everyone negative
        # about a massacre says nothing about how anyone framed it.
        members = [
            _member(1, "RU", "negative"),
            _member(1, "RU", "negative"),
            _member(1, "US", "negative"),
            _member(1, "US", "negative"),
        ]
        report = measure_discrimination(members)
        assert report.stories_unanimous == 1
        assert report.unanimous_share == 1.0

    def test_a_single_bloc_story_is_skipped_not_counted_as_unanimous(self) -> None:
        # One bloc cannot disagree with itself. Counting it as agreement would
        # inflate the very number this measurement exists to read.
        members = [_member(1, "US", "negative"), _member(1, "US", "negative")]
        report = measure_discrimination(members)
        assert report.stories_considered == 0
        assert report.stories_skipped == 1
        assert report.unanimous_share is None

    def test_a_bloc_with_one_article_does_not_get_a_lean(self) -> None:
        members = [
            _member(1, "RU", "negative"),
            _member(1, "RU", "negative"),
            _member(1, "US", "positive"),
        ]
        report = measure_discrimination(members)
        assert report.stories_considered == 0

    def test_unlabelled_members_are_dropped(self) -> None:
        members = [
            _member(1, "RU", None),
            _member(1, "RU", "negative"),
            _member(1, "US", "negative"),
        ]
        report = measure_discrimination(members)
        assert report.stories_considered == 0  # RU now has one usable article

    def test_reports_the_spread_per_bloc(self) -> None:
        members = [
            _member(1, "RU", "negative"),
            _member(1, "RU", "negative"),
            _member(1, "US", "neutral"),
            _member(1, "US", "neutral"),
            _member(2, "RU", "negative"),
            _member(2, "RU", "negative"),
            _member(2, "US", "negative"),
            _member(2, "US", "negative"),
        ]
        report = measure_discrimination(members)
        assert report.stories_considered == 2
        assert report.stories_unanimous == 1
        assert report.per_bloc["RU"] == {"negative": 2}
        assert report.per_bloc["US"] == {"neutral": 1, "negative": 1}

    def test_empty_input_reports_nothing_rather_than_dividing_by_zero(self) -> None:
        report = measure_discrimination([])
        assert report.stories_considered == 0
        assert report.unanimous_share is None


class TestMeasureAgreement:
    def test_counts_agreement(self) -> None:
        report = measure_agreement([("a", "negative", "negative"), ("b", "neutral", "positive")])
        assert report.compared == 2
        assert report.agreed == 1
        assert report.agreement == 0.5

    def test_unscored_rows_are_reported_not_silently_dropped(self) -> None:
        # A model that refuses half the corpus is a finding, not a footnote.
        report = measure_agreement([("a", "negative", None), ("b", "negative", "negative")])
        assert report.unscored == 1
        assert report.compared == 1
        assert report.agreement == 1.0

    def test_rows_without_a_stored_label_are_not_compared(self) -> None:
        report = measure_agreement([("a", None, "negative")])  # type: ignore[list-item]
        assert report.compared == 0
        assert report.unscored == 0

    def test_builds_a_confusion_matrix(self) -> None:
        report = measure_agreement(
            [
                ("a", "negative", "neutral"),
                ("b", "negative", "neutral"),
                ("c", "negative", "negative"),
            ]
        )
        assert report.confusion_row("negative") == {"neutral": 2, "negative": 1}

    def test_keeps_the_disagreeing_headlines(self) -> None:
        # The shape of the disagreement matters more than its size: the two
        # scorers are answering slightly different questions by design.
        report = measure_agreement([("Regime slaughters civilians", "negative", "neutral")])
        assert report.disagreements[0].headline == "Regime slaughters civilians"
        assert report.disagreements[0].vader == "negative"
        assert report.disagreements[0].model == "neutral"

    def test_caps_the_examples_it_keeps(self) -> None:
        pairs = [(f"h{i}", "negative", "positive") for i in range(100)]
        report = measure_agreement(pairs, max_examples=5)
        assert len(report.disagreements) == 5
        assert report.compared == 100

    def test_no_input_reports_nothing_rather_than_dividing_by_zero(self) -> None:
        assert measure_agreement([]).agreement is None


class TestToneLlmParsing:
    def test_reads_a_valid_label(self) -> None:
        assert tone_llm.tone_from_payload({"tone": "Negative", "reason": "x"}) == "negative"

    def test_rejects_a_label_outside_the_rubric(self) -> None:
        # A model inventing "mixed" must skip the row, not widen the schema.
        assert tone_llm.tone_from_payload({"tone": "mixed"}) is None

    def test_rejects_a_non_dict(self) -> None:
        assert tone_llm.tone_from_payload("negative") is None
        assert tone_llm.tone_from_payload(None) is None

    def test_extracts_json_from_surrounding_chatter(self) -> None:
        body = 'Sure! Here you go:\n{"tone": "neutral", "reason": "plain"}\nHope that helps.'
        assert tone_llm.parse_response(body) == "neutral"

    def test_unparseable_text_returns_none(self) -> None:
        assert tone_llm.parse_response("no json here") is None
        assert tone_llm.parse_response("") is None

    def test_prompt_states_that_grim_facts_are_not_negative_tone(self) -> None:
        # The distinction the whole measurement rests on. If this line is ever
        # dropped the model collapses back into VADER's question.
        prompt = tone_llm.build_prompt("40 killed in earthquake")
        assert "Grim facts alone are NOT negative tone" in prompt
        assert "40 killed in earthquake" in prompt
