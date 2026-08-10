"""Tests for `app.stories.vectorize` — tokenizer, tf-idf, cosine."""

from __future__ import annotations

import pytest

from app.stories.cluster import MIN_SHARED_TOKENS
from app.stories.vectorize import build_idf, cosine, tokenize, vectorize


class TestTokenize:
    def test_lowercase_and_punctuation(self) -> None:
        assert tokenize("Quake Strikes Tokyo, dozens injured!") == [
            "quake",
            "strikes",
            "tokyo",
            "dozens",
            "injured",
        ]

    def test_stopwords_and_short_tokens_dropped(self) -> None:
        assert tokenize("The war in the US is on") == ["war"]

    def test_numbers_kept(self) -> None:
        assert "2026" in tokenize("Earthquake of magnitude 7.1 in 2026")


class TestIdfAndVectors:
    def test_ubiquitous_token_downweighted(self) -> None:
        titles = [["news", "quake"], ["news", "election"], ["news", "flood"]]
        idf = build_idf(titles)
        assert idf["news"] < idf["quake"]

    def test_vector_contains_only_title_tokens(self) -> None:
        idf = build_idf([["quake", "tokyo"], ["flood", "lagos"]])
        vec = vectorize(["quake", "tokyo"], idf)
        assert set(vec) == {"quake", "tokyo"}


class TestCosine:
    def test_identical_vectors(self) -> None:
        v = {"quake": 1.0, "tokyo": 2.0}
        assert cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert cosine({"quake": 1.0}, {"election": 1.0}) == 0.0

    def test_known_overlap(self) -> None:
        a = {"quake": 1.0, "tokyo": 1.0}
        b = {"quake": 1.0, "osaka": 1.0}
        assert cosine(a, b) == pytest.approx(0.5)

    def test_empty_vector_is_zero(self) -> None:
        assert cosine({}, {"quake": 1.0}) == 0.0


class TestExplainerFormula:
    """A stock headline formula is a slot, not a subject (#913).

    "What we know so far" appears on eight headlines in a 72-hour window of
    6,561, so document frequency reads it as one of the most discriminating
    things in the corpus — `know` scored 7.016 against `earthquake` at 5.897.
    Two explainers about unrelated events then share the heaviest tokens they
    have, and the cluster that results is a bag of everything the formula was
    used on that week.

    These are function words, like the `says` / `live` / `report` already in
    the list. Nothing in the world is ever about them.
    """

    def test_interrogative_words_are_dropped(self) -> None:
        assert tokenize("What to Know About Iraq's Militias") == ["iraq", "militias"]

    def test_explainer_headlines_about_different_events_cannot_reach_a_join(self) -> None:
        """`far` survives — it is half of "far right" — so the two headlines
        still share it. One token is below the two a join requires, which is
        the guarantee that matters: the formula alone can no longer carry a
        pair over the threshold."""
        berlin = set(tokenize("Berlin Pride attack: What we know so far"))
        japan = set(tokenize("Japan earthquake: What we know so far"))
        assert len(berlin & japan) < MIN_SHARED_TOKENS

    def test_the_same_event_still_survives_the_formula(self) -> None:
        a = tokenize("Berlin Pride attack: What we know so far")
        b = tokenize("What we know so far about the Berlin Pride ramming attack")
        assert {"berlin", "pride", "attack"} <= set(a) & set(b)

    def test_who_the_agency_is_not_a_stopword(self) -> None:
        """81 headlines in one window carry `who`, and one of them is the
        health agency reporting on an Ebola outbreak. Dropping it would cost a
        subject to spare a pronoun."""
        headline = "DRC's Ebola outbreak began months before it was declared, says WHO"
        assert "who" in tokenize(headline)

    def test_far_right_keeps_its_meaning(self) -> None:
        """`far` was a candidate for removal — it is in the formula. It is also
        half of a political label, so it stays."""
        assert "far" in tokenize("Police urged to crack down on far right protesters")
