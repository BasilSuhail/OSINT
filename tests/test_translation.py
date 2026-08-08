"""Translating a desk the gazetteers cannot read (#835).

Al Jazeera's Arabic desk publishes 218 items a day and produced 0 of 25 rows
with a country, 0 positioned, and one constant severity, because every
gazetteer here is Latin-script: 0 Arabic terms of 426, 0 Arabic spellings
across 7,484 cities.

Every test is offline. The model call is one injected function; everything
that decides *whether* to spend it, and what to do with what comes back, is
pure.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.enrichment import translation

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

#: Real headlines from the feed, used as fixtures so the rules are exercised
#: against what the desk actually publishes.
ARABIC = "قصة تحوّل دانييل أورتيغا من محاربة الاستبداد إلى احتكار السلطة"
ARABIC_2 = "تنكيل وتعذيب في عرض البحر.. شهادات ناشطي أسطول غزة"
ENGLISH = "Police make 49 arrests in Edinburgh city centre crackdown"


def _generate(answer: str | None = "A translated headline"):
    def generate(prompt: str, *, model: str) -> str | None:
        generate.calls.append((prompt, model))
        return answer

    generate.calls = []
    return generate


class TestWhetherToSpendACall:
    def test_an_arabic_headline_from_an_arabic_desk_is_translated(self) -> None:
        assert translation.needs_translation(ARABIC, declared_language="ar")

    def test_an_english_desk_is_never_translated(self) -> None:
        """The feed's declaration decides. Guessing per row would spend calls
        on English headlines that merely quote a name."""
        assert not translation.needs_translation(ENGLISH, declared_language="en")
        assert not translation.needs_translation(ARABIC, declared_language="en")
        assert not translation.needs_translation(ARABIC, declared_language=None)

    def test_a_latin_row_from_a_non_english_desk_needs_nothing(self) -> None:
        """A transliterated wire item on an Arabic desk is already readable."""
        assert not translation.needs_translation(ENGLISH, declared_language="ar")

    def test_a_headline_that_only_quotes_a_foreign_name_is_left_alone(self) -> None:
        """Measured: this scores 0.25 while every real headline on the desk
        scores 1.00, so the gate has margin on both sides rather than sitting
        on top of one of them."""
        mostly_english = "Aid convoy reaches Gaza, says الأونروا"
        assert translation.non_latin_share(mostly_english) == pytest.approx(0.25, abs=0.02)
        assert not translation.needs_translation(mostly_english, declared_language="ar")

    def test_a_real_headline_from_the_desk_is_unambiguous(self) -> None:
        assert translation.non_latin_share(ARABIC) == 1.0
        assert translation.non_latin_share(ENGLISH) == 0.0

    def test_empty_text_costs_nothing(self) -> None:
        assert not translation.needs_translation("", declared_language="ar")
        assert not translation.needs_translation(None, declared_language="ar")


class TestReadingTheAnswer:
    def test_a_plain_answer_is_taken(self) -> None:
        assert translation.clean_response("Gaza flotilla activists describe abuse at sea") == (
            "Gaza flotilla activists describe abuse at sea"
        )

    def test_an_empty_answer_is_a_failure_not_a_headline(self) -> None:
        """The 4B model returned empty on three of four real headlines. An
        empty translation stored as a title is worse than none: the row looks
        readable and says nothing."""
        assert translation.clean_response("") is None
        assert translation.clean_response("   ") is None
        assert translation.clean_response(None) is None

    def test_a_model_announcing_itself_does_not_get_into_the_headline(self) -> None:
        assert translation.clean_response('Here is the translation: "Ortega tightens grip"') == (
            "Ortega tightens grip"
        )
        assert translation.clean_response("Translation: Ortega tightens grip") == (
            "Ortega tightens grip"
        )

    def test_a_runaway_response_is_refused(self) -> None:
        assert translation.clean_response("x" * (translation.MAX_TRANSLATION_CHARS + 1)) is None

    def test_whitespace_is_normalised(self) -> None:
        assert translation.clean_response("Ortega\n\n  tightens   grip") == "Ortega tightens grip"


class TestApplyingItToARow:
    def _payload(self, title: str = ARABIC) -> dict:
        return {"title": title, "source_url": "https://www.aljazeera.net/x"}

    def test_the_english_text_lands_where_everything_reads_it(self) -> None:
        """`title` is what the geo resolver, readable_claim, the search vector
        and clustering all read. A translation nothing reads changes nothing."""
        out = translation.apply(
            self._payload(),
            declared_language="ar",
            generate=_generate("Ortega tightens grip"),
            now=NOW,
        )
        assert out["title"] == "Ortega tightens grip"

    def test_the_original_is_kept_verbatim(self) -> None:
        """A machine translation is not the publisher's words. The field an
        audit or a citation must use has to survive intact."""
        out = translation.apply(
            self._payload(), declared_language="ar", generate=_generate(), now=NOW
        )
        assert out["title_original"] == ARABIC

    def test_the_translation_says_who_made_it_and_when(self) -> None:
        out = translation.apply(
            self._payload(), declared_language="ar", generate=_generate(), now=NOW
        )
        note = out["title_translation"]
        assert note["status"] == "ok"
        assert note["model"] == translation.TRANSLATION_MODEL
        assert note["method_version"] == translation.TRANSLATION_METHOD_VERSION
        assert note["translated_at"] == NOW.isoformat()

    def test_a_failure_keeps_the_original_and_admits_it(self) -> None:
        """A desk that silently stopped translating must be visible, not
        merely quiet."""
        out = translation.apply(
            self._payload(), declared_language="ar", generate=_generate(None), now=NOW
        )
        assert out["title"] == ARABIC
        assert "title_original" not in out
        assert out["title_translation"]["status"] == "failed"
        assert out["title_translation"]["attempted_at"] == NOW.isoformat()

    def test_a_model_that_raises_is_not_an_outage(self) -> None:
        def explode(prompt: str, *, model: str):
            raise RuntimeError("ollama is busy")

        out = translation.apply(self._payload(), declared_language="ar", generate=explode, now=NOW)
        assert out["title"] == ARABIC
        assert out["title_translation"]["status"] == "failed"

    def test_an_english_feed_is_returned_untouched(self) -> None:
        generate = _generate()
        payload = {"title": ENGLISH}
        assert translation.apply(payload, declared_language="en", generate=generate) == payload
        assert generate.calls == [], "an English desk spent a model call"

    def test_two_rows_from_one_desk_each_get_their_own_call(self) -> None:
        generate = _generate()
        for title in (ARABIC, ARABIC_2):
            translation.apply({"title": title}, declared_language="ar", generate=generate, now=NOW)
        assert len(generate.calls) == 2

    def test_the_prompt_asks_for_a_headline_and_nothing_else(self) -> None:
        generate = _generate()
        translation.apply(self._payload(), declared_language="ar", generate=generate, now=NOW)
        prompt, model = generate.calls[0]
        assert ARABIC in prompt
        assert "translation only" in prompt.lower()
        assert model == translation.TRANSLATION_MODEL


class TestTheModelChoiceIsMeasured:
    def test_the_model_is_the_one_that_worked(self) -> None:
        """Measured on this feed's real headlines: llama3.2:3b at 2.2 s each
        and accurate; the 4B thinking model at 134 s and empty three times of
        four. Chosen on that, not on parameter count."""
        assert translation.TRANSLATION_MODEL == "llama3.2:3b"

    @pytest.mark.parametrize("share,expected", [(0.0, False), (0.25, False), (1.0, True)])
    def test_the_script_gate_is_a_share_not_a_flag(self, share: float, expected: bool) -> None:
        latin = "a" * int(20 * (1 - share))
        arabic = "ع" * int(20 * share)
        assert translation.needs_translation(latin + arabic, declared_language="ar") is expected


class TestTheArabicDeskInTheRegistry:
    """One organisation, two desks, one teller (#641)."""

    def test_both_al_jazeera_desks_collapse_to_one_owner(self) -> None:
        from app.sources.rss_registry import content_owner_map

        owners = content_owner_map()
        assert owners["rss-aljazeera-arabic"] == owners["rss-aljazeera"]

    def test_the_arabic_desk_declares_its_language(self) -> None:
        from app.sources.rss_registry import load_feed_configs

        configs = {c.source: c for c in load_feed_configs()}
        assert configs["rss-aljazeera-arabic"].language == "ar"
        assert configs["rss-aljazeera"].language == "en"

    def test_every_other_feed_still_defaults_to_english(self) -> None:
        """A field nobody set must not quietly start spending model calls."""
        from app.sources.rss_registry import load_feed_configs

        non_english = {c.source for c in load_feed_configs() if c.language != "en"}
        assert non_english == {"rss-aljazeera-arabic"}

    def test_the_arabic_desk_claims_no_geotagging_bias(self) -> None:
        """The English desk carries default_country=QA as a city hint. A
        pan-Arab desk covering the whole region should not have its gazetteer
        lookups pulled toward Qatar."""
        from app.sources.rss_registry import load_feed_configs

        configs = {c.source: c for c in load_feed_configs()}
        assert configs["rss-aljazeera-arabic"].default_country is None
