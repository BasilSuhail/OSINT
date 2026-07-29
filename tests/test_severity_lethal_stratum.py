"""Stratified sampling so the floor metric stops resting on four rows (#665).

Every "zero missed deaths" figure this project has published came from four
headlines. The repair is a second block enriched for deaths — and the way that
block is chosen is the whole design, because the obvious way is wrong.
"""

from __future__ import annotations

import pytest

from app.severity import agreement, audit

HEADER = (
    "| headline | model severity | model band | model rationale "
    "| human severity | human band | rationale ok | stratum |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _row(headline, m_sev, m_band, h_band, stratum, ok="ok", h_sev=""):
    return (
        f"| {headline} | {m_sev} | {m_band} | a reason | {h_sev} | {h_band} | {ok} | {stratum} |\n"
    )


class TestSelectingTheLethalBlock:
    @pytest.mark.parametrize(
        "headline",
        [
            "Three killed in a bombing",
            "Six dead after building collapse",
            "Massacre reported in border village",
            "Two died in the flooding",
        ],
    )
    def test_a_death_word_marks_a_headline_lethal(self, headline):
        assert audit.looks_lethal(headline) is True

    @pytest.mark.parametrize(
        "headline",
        [
            "Workers strike over pay",
            "Stock market crash wipes billions",
            "Central bank raises interest rates",
        ],
    )
    def test_ordinary_news_is_not(self, headline):
        assert audit.looks_lethal(headline) is False

    def test_selection_never_consults_the_model(self):
        # The trap this issue exists to avoid. A floor violation is "the human
        # says a death and the model scored it below 0.60". Selecting on the
        # model's own band would exclude exactly those rows by construction,
        # turning a recall metric into a precision one without saying so.
        headline = "Three killed in a bombing"

        assert audit.looks_lethal(headline) is True
        # No severity, no band, no verdict — only the headline text.
        assert audit.looks_lethal.__code__.co_argcount == 1

    def test_the_keyword_rule_has_blind_spots_and_that_is_why_both_blocks_exist(self):
        # #649 found this one: the list carries `died`, not `dies`. The lethal
        # block is enriched, never exhaustive — the random block is what keeps
        # the sheet honest about what the keyword rule cannot see.
        assert audit.looks_lethal("'Five Star Chef' winner Dom Taylor dies at 44") is False


class TestScoringTheTwoBlocks:
    def test_band_agreement_ignores_the_lethal_block(self):
        # Lethal headlines are the easy ones to band. Counting an enriched block
        # of them would inflate the rate by construction.
        rows = agreement.parse_sheet(
            HEADER
            + _row("Council debates budget", 0.05, "routine", "routine", "random")
            + _row("Protest blocks the port", 0.5, "violence", "tension", "random")
            + _row("Three killed in a bombing", 0.7, "grave", "grave", "lethal")
            + _row("Six dead in a strike", 0.7, "grave", "grave", "lethal")
        )

        result = agreement.score(rows)

        # 1 of 2 unbiased rows agree — the two lethal rows would have made it 3/4.
        assert result["n_banded"] == 2
        assert result["band_agreement"] == 0.5

    def test_floor_violations_count_every_lethal_row(self):
        # The opposite rule, and the entire point: more lethal rows is better.
        rows = agreement.parse_sheet(
            HEADER
            + _row("Council debates budget", 0.05, "routine", "routine", "random")
            + _row("Three killed in a bombing", 0.30, "tension", "grave", "lethal")
            + _row("Six dead in a strike", 0.70, "grave", "grave", "lethal")
        )

        result = agreement.score(rows)

        assert result["n_lethal"] == 2
        assert result["floor_violations"] == 1

    def test_the_denominator_is_published_next_to_the_rate(self):
        # Nobody should be able to quote "0 floor violations" again without
        # seeing how many lethal rows it was measured on.
        rows = agreement.parse_sheet(
            HEADER
            + _row("Council debates budget", 0.05, "routine", "routine", "random")
            + _row("Three killed in a bombing", 0.7, "grave", "grave", "lethal")
        )

        report = agreement.render(agreement.score(rows))

        assert "of 1 lethal rows" in report
        assert "unbiased rows" in report


class TestTheOldSheetStillWorks:
    def test_a_sheet_without_a_stratum_column_reads_as_one_random_block(self):
        # The filled sheet that produced the published 0.860 has seven columns.
        # It must keep parsing, and keep meaning what it meant.
        old_header = (
            "| headline | model severity | model band | model rationale "
            "| human severity | human band | rationale ok |\n"
            "|---|---|---|---|---|---|---|\n"
        )
        old_row = "| Three killed in a bombing | 0.7 | grave | a reason |  | grave | ok |\n"

        rows = agreement.parse_sheet(old_header + old_row)

        assert len(rows) == 1
        assert rows[0]["stratum"] == "random"
        assert agreement.score(rows)["band_agreement"] == 1.0


class TestNotDestroyingTheHumansWork:
    def test_a_filled_sheet_is_not_overwritten(self, tmp_path):
        # `make severity-audit` writes to a fixed path. Fifty hand-graded rows
        # are hours of work and the only evidence the grader works at all.
        sheet = tmp_path / "severity-audit-sheet.md"
        sheet.write_text(
            HEADER + _row("Three killed in a bombing", 0.7, "grave", "grave", "lethal")
        )

        assert audit.has_human_grades(sheet) is True

    def test_an_unfilled_sheet_is_fair_game(self, tmp_path):
        sheet = tmp_path / "severity-audit-sheet.md"
        sheet.write_text(
            HEADER + _row("Three killed in a bombing", 0.7, "grave", "", "lethal", ok="")
        )

        assert audit.has_human_grades(sheet) is False

    def test_a_missing_sheet_is_fair_game(self, tmp_path):
        assert audit.has_human_grades(tmp_path / "nothing-here.md") is False
