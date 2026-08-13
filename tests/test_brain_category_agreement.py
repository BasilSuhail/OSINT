"""Tests for the category audit sheet and the agreement it publishes (#951)."""

from __future__ import annotations

from app.brain import category_agreement as ca
from app.brain.category_audit import RANDOM_STRATUM, READ_STRATUM, build_sheet, has_human_labels

BLANK_SHEET = build_sheet(
    [
        {"story_id": 1, "titles": ["Quake kills 20 in Chile"], "stratum": RANDOM_STRATUM},
        {"story_id": 2, "titles": ["Shares close higher in Seoul"], "stratum": READ_STRATUM},
    ],
    created="2026-08-13 00:00 UTC",
)

FILLED_SHEET = """
| story | headlines | human category | enum ok | would rather | stratum |
|---|---|---|---|---|---|
| 1 | Quake kills 20 in Chile | disaster | yes |  | random |
| 2 | Shares close higher in Seoul | economy | yes |  | random |
| 3 | Total eclipse crosses Europe | other | no | science | read |
| 4 | Gunman held after shooting | other | no | crime | read |
| 5 | Some story nobody labelled |  |  |  | random |
"""


class TestParse:
    def test_a_blank_sheet_carries_no_labels(self) -> None:
        assert ca.scored_rows(ca.parse_sheet(BLANK_SHEET)) == []

    def test_every_data_row_is_parsed(self) -> None:
        assert len(ca.parse_sheet(FILLED_SHEET)) == 5

    def test_an_unlabelled_row_is_dropped_rather_than_counted(self) -> None:
        # The contract the severity sheet set: a blank human side is never
        # assumed correct, it simply does not count.
        assert len(ca.scored_rows(ca.parse_sheet(FILLED_SHEET))) == 4

    def test_headlines_survive_the_round_trip(self) -> None:
        rows = ca.parse_sheet(BLANK_SHEET)
        assert rows[0]["titles"] == ["Quake kills 20 in Chile"]

    def test_the_header_underline_is_not_a_row(self) -> None:
        assert all(r["story_id"] != 0 for r in ca.parse_sheet(FILLED_SHEET))


class TestForcedRate:
    def test_counts_only_answered_rows(self) -> None:
        forced = ca.forced_rate(ca.parse_sheet(FILLED_SHEET))
        assert forced["answered"] == 4
        assert forced["forced"] == 2
        assert forced["rate"] == 0.5

    def test_collects_what_the_reviewer_would_rather_have_said(self) -> None:
        forced = ca.forced_rate(ca.parse_sheet(FILLED_SHEET))
        assert dict(forced["would_rather"]) == {"science": 1, "crime": 1}

    def test_an_unanswered_sheet_reports_no_rate(self) -> None:
        assert ca.forced_rate(ca.parse_sheet(BLANK_SHEET))["rate"] is None


class TestAgreement:
    def test_a_perfect_model_agrees_everywhere(self) -> None:
        rows = ca.parse_sheet(FILLED_SHEET)
        predictions = {1: "disaster", 2: "economy", 3: "other", 4: "other"}
        assert ca.agreement(rows, predictions)["agreement"] == 1.0

    def test_disagreement_is_recorded_by_pair(self) -> None:
        rows = ca.parse_sheet(FILLED_SHEET)
        predictions = {1: "conflict", 2: "economy", 3: "other", 4: "other"}
        result = ca.agreement(rows, predictions)
        assert result["agreement"] == 0.75
        assert result["confusion"][("disaster", "conflict")] == 1

    def test_strata_are_reported_apart(self) -> None:
        # The read block is deliberately not an unbiased draw, so it must never
        # be silently folded into the headline figure.
        rows = ca.parse_sheet(FILLED_SHEET)
        predictions = {1: "disaster", 2: "economy", 3: "conflict", 4: "conflict"}
        by = ca.agreement(rows, predictions)["by_stratum"]
        assert by["random"]["agreement"] == 1.0
        assert by["read"]["agreement"] == 0.0

    def test_a_row_the_model_was_not_asked_about_is_not_counted(self) -> None:
        rows = ca.parse_sheet(FILLED_SHEET)
        assert ca.agreement(rows, {1: "disaster"})["n"] == 1


class TestSheet:
    def test_a_fresh_sheet_is_not_treated_as_filled(self, tmp_path) -> None:
        path = tmp_path / "sheet.md"
        path.write_text(BLANK_SHEET)
        assert has_human_labels(path) is False

    def test_a_filled_sheet_is_protected(self, tmp_path) -> None:
        path = tmp_path / "sheet.md"
        path.write_text(FILLED_SHEET)
        assert has_human_labels(path) is True

    def test_a_missing_sheet_is_not_filled(self, tmp_path) -> None:
        assert has_human_labels(tmp_path / "absent.md") is False

    def test_the_sheet_shows_no_model_answer(self) -> None:
        # This sheet compares several models, so printing one of them beside
        # the blank column would pull the labels toward it.
        assert "model category" not in BLANK_SHEET
        assert "human category" in BLANK_SHEET

    def test_a_pipe_in_a_headline_cannot_break_the_table(self) -> None:
        sheet = build_sheet(
            [{"story_id": 9, "titles": ["Latest news bulletin | Evening"], "stratum": "random"}],
            created="2026-08-13 00:00 UTC",
        )
        rows = ca.parse_sheet(sheet)
        assert len(rows) == 1
        assert rows[0]["story_id"] == 9
