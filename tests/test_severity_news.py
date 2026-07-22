"""LLM-graded news severity and its guards (#591).

The model is another fallible annotator, never a judge (#378/#386). Every guard
below exists because something already went wrong once: #514/#553 swept 138
stored gists carrying invented figures.
"""

from __future__ import annotations

import pytest

from app.severity import news, scale


class TestParsing:
    def test_reads_a_well_formed_verdict(self):
        verdict = news.parse_response(
            '{"severity": 0.85, "rationale": "12 killed in a market bombing"}',
            headline="12 killed in a market bombing in Kano",
        )

        assert verdict is not None
        assert verdict.value == 0.85
        assert verdict.method == news.METHOD

    def test_tolerates_prose_around_the_json(self):
        """Small models wrap JSON in chatter. Extract it rather than fail."""
        verdict = news.parse_response(
            "Here is my answer:\n"
            '{"severity": 0.3, "rationale": "Rail strike over pay"}\n'
            "Hope that helps!",
            headline="Rail strike over pay enters second week",
        )

        assert verdict is not None and verdict.value == 0.3

    @pytest.mark.parametrize("body", ["not json at all", "", "{}", '{"severity": 0.5}'])
    def test_rejects_unusable_responses(self, body):
        assert news.parse_response(body, headline="anything") is None

    def test_rejects_a_severity_outside_the_scale(self):
        assert news.parse_response('{"severity": 4, "rationale": "very bad"}', headline="x") is None


class TestNumeralGuard:
    def test_rejects_a_rationale_citing_a_figure_the_headline_lacks(self):
        """#514: the model must not invent a death toll."""
        verdict = news.parse_response(
            '{"severity": 0.9, "rationale": "47 killed in the blast"}',
            headline="Deadly blast reported in the capital",
        )

        assert verdict is None

    def test_accepts_a_figure_the_headline_carries(self):
        verdict = news.parse_response(
            '{"severity": 0.9, "rationale": "47 killed in the blast"}',
            headline="47 killed in blast at capital market",
        )

        assert verdict is not None

    def test_accepts_a_rationale_with_no_figures(self):
        verdict = news.parse_response(
            '{"severity": 0.7, "rationale": "Gunmen killed villagers in an armed attack"}',
            headline="Gunmen attack village, several dead",
        )

        assert verdict is not None


class TestEuphemismGuard:
    def test_rejects_a_softened_lethal_rationale(self):
        """No cake words above the lethal floor."""
        verdict = news.parse_response(
            '{"severity": 0.8, "rationale": "An unfortunate incident occurred"}',
            headline="Dozens dead after attack on market",
        )

        assert verdict is None

    def test_allows_the_same_wording_when_the_score_is_routine(self):
        verdict = news.parse_response(
            '{"severity": 0.1, "rationale": "Minor incident at a council meeting"}',
            headline="Minor incident at a council meeting",
        )

        assert verdict is not None


class TestKeywordFallback:
    """The ingest path keeps working when the model does not."""

    def test_a_lethal_headline_reaches_the_lethal_floor(self):
        verdict = news.keyword_verdict("50 killed in market bombing", "")

        assert verdict.value >= scale.LETHAL_FLOOR
        assert verdict.method == news.FALLBACK_METHOD

    def test_a_protest_stays_below_it(self):
        """The old rule scored this identically to a massacre."""
        verdict = news.keyword_verdict("Workers strike over pay", "")

        assert verdict.value < scale.LETHAL_FLOOR

    def test_routine_news_lands_low(self):
        verdict = news.keyword_verdict("Council approves budget for new library", "")

        assert verdict.value < 0.4

    def test_always_states_a_reason(self):
        assert news.keyword_verdict("anything at all", "").rationale


class TestRubricNumeralsAreNotInventions:
    """Caught in live testing: a correct verdict was thrown away (#591).

    The model answered 0.8 for "At least 47 dead after airstrike" with the
    rationale "47 confirmed deaths exceed the 10-death threshold requiring a
    minimum score of 0.80". The numeral guard saw 10 and 0.80, neither in the
    headline, and rejected it — discarding a right answer for quoting the
    prompt back.
    """

    def test_a_rationale_quoting_the_rubric_survives(self):
        verdict = news.parse_response(
            '{"severity": 0.8, "rationale": "47 confirmed deaths from an airstrike exceed '
            'the 10-death threshold requiring a minimum score of 0.80."}',
            headline="At least 47 dead after airstrike hits residential block",
        )

        assert verdict is not None
        assert verdict.value == 0.8

    def test_an_invented_casualty_figure_is_still_rejected(self):
        """The exemption must not become a hole the guard falls through."""
        verdict = news.parse_response(
            '{"severity": 0.9, "rationale": "312 killed in the strike"}',
            headline="Deadly airstrike hits residential block",
        )

        assert verdict is None
