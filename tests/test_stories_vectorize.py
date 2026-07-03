"""Tests for `app.stories.vectorize` — tokenizer, tf-idf, cosine."""

from __future__ import annotations

import pytest

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
