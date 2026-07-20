"""Numeral grounding (#514) — a gist may only carry figures its headlines carry."""

from app.brain import numerals


def test_extracts_plain_integers():
    assert numerals.extract_numerals("at least 12 dead") == {12.0}


def test_strips_thousands_separators():
    assert numerals.extract_numerals("surpassed 2,800 cases") == {2800.0}


def test_keeps_decimals_whole():
    # "5.1" must not tokenise to a bare 5 — that produced false negatives in the
    # first sweep, because a magnitude then looked like a casualty count.
    assert numerals.extract_numerals("magnitude 5.1 earthquake") == {5.1}


def test_reads_written_cardinals():
    assert numerals.extract_numerals("at least five dead and ten injured") == {5.0, 10.0}


def test_reads_hyphenated_written_cardinals():
    assert numerals.extract_numerals("twenty-five wounded") == {25.0}


def test_applies_scale_words_to_a_preceding_number():
    assert numerals.extract_numerals("1.5 million displaced") == {1500000.0}


def test_reads_written_number_with_scale_word():
    assert numerals.extract_numerals("three thousand evacuated") == {3000.0}


def test_reads_numbers_glued_to_a_unit():
    assert numerals.extract_numerals("an 18-month dry spell") == {18.0}


def test_reads_percentages():
    assert numerals.extract_numerals("inflation hit 12%") == {12.0}


def test_ignores_ordinals():
    # Rank, not quantity: "the third strike" carries no figure to ground.
    assert numerals.extract_numerals("the third strike this week") == set()


def test_text_without_figures_yields_nothing():
    assert numerals.extract_numerals("Border clashes reported near the frontier") == set()


def test_unsupported_matches_written_gist_against_digit_headline():
    # The whole point of normalising both sides: "five" is grounded by "5".
    assert (
        numerals.unsupported_numerals(
            "Five people died in the blast.", ["Blast kills 5 in market district"]
        )
        == []
    )


def test_unsupported_flags_an_invented_casualty_figure():
    # Story 12662, the case that opened #514: one dead became five.
    gist = (
        "A magnitude 5.1 earthquake struck central Peru, resulting in at "
        "least five deaths and ten injuries."
    )
    titles = [
        "Magnitude 5.1 earthquake in central Peru leaves at least one dead and ten injured",
    ]
    assert numerals.unsupported_numerals(gist, titles) == [5.0]


def test_unsupported_flags_a_drifted_age():
    # 80 -> 81 is invention too, not a rounding artefact. No exemption for ages.
    assert numerals.unsupported_numerals(
        "The pianist dies at 81.", ["Jazz pianist dies at 80"]
    ) == [81.0]


def test_unsupported_grounds_across_several_headlines():
    gist = "The strike killed 12 and wounded 30."
    titles = ["Strike kills 12", "Thirty wounded in overnight strike"]
    assert numerals.unsupported_numerals(gist, titles) == []


def test_unsupported_returns_offenders_sorted():
    out = numerals.unsupported_numerals("9 dead, 4 missing, 40 hurt", ["Four missing after flood"])
    assert out == [9.0, 40.0]


def test_unsupported_passes_a_gist_with_no_figures():
    assert (
        numerals.unsupported_numerals("Clashes continue at the border.", ["Border clashes"]) == []
    )


def test_unsupported_flags_every_figure_when_headlines_are_empty():
    assert numerals.unsupported_numerals("Seven dead.", []) == [7.0]
