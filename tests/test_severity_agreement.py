"""Scoring the filled human sheet (#593).

Severity is a number, so exact match is the wrong test — a human writing 0.62
against the model's 0.60 is agreement, not error. Band agreement is the
headline; floor violations are counted on their own, because a missed death is
worth more than ten near-miss band disagreements.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.severity import agreement, news

HEADER = (
    "| headline | model severity | model band | model rationale "
    "| human severity | human band | rationale ok |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _sheet(*rows: str) -> str:
    return HEADER + "".join(rows)


def _row(headline, m_sev, m_band, m_reason, h_sev="", h_band="", ok=""):
    return f"| {headline} | {m_sev} | {m_band} | {m_reason} | {h_sev} | {h_band} | {ok} |\n"


class TestParsing:
    def test_reads_a_filled_row(self):
        rows = agreement.parse_sheet(
            _sheet(_row("3 killed", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        assert len(rows) == 1
        assert rows[0]["model_severity"] == 0.6
        assert rows[0]["human_band"] == "grave"

    def test_skips_a_row_the_human_left_blank(self):
        """Never assumed correct — an ungraded row is simply not counted."""
        rows = agreement.parse_sheet(_sheet(_row("3 killed", 0.6, "grave", "three killed")))

        assert rows == []

    def test_counts_a_row_graded_only_on_the_band(self):
        """The band is the headline metric; the numeric column is optional."""
        rows = agreement.parse_sheet(
            _sheet(_row("3 killed", 0.6, "grave", "three killed", "", "violence", ""))
        )

        assert len(rows) == 1
        assert rows[0]["human_severity"] is None

    def test_ignores_the_header_and_separator(self):
        assert agreement.parse_sheet(HEADER) == []


class TestBandAgreement:
    def test_all_matching_is_total_agreement(self):
        rows = agreement.parse_sheet(
            _sheet(
                _row("a", 0.6, "grave", "r", 0.6, "grave", "ok"),
                _row("b", 0.1, "routine", "r", 0.1, "routine", "ok"),
            )
        )

        assert agreement.score(rows)["band_agreement"] == 1.0

    def test_half_matching_is_half(self):
        rows = agreement.parse_sheet(
            _sheet(
                _row("a", 0.6, "grave", "r", 0.6, "grave", "ok"),
                _row("b", 0.1, "routine", "r", 0.5, "violence", "ok"),
            )
        )

        assert agreement.score(rows)["band_agreement"] == 0.5

    def test_reports_how_many_rows_it_counted(self):
        rows = agreement.parse_sheet(_sheet(_row("a", 0.6, "grave", "r", 0.6, "grave", "ok")))

        assert agreement.score(rows)["n"] == 1


class TestFloorViolations:
    """The failure that matters most: a death the model scored as not-a-death."""

    def test_a_human_death_scored_below_the_floor_is_a_violation(self):
        rows = agreement.parse_sheet(
            _sheet(_row("bomb kills 3", 0.3, "tension", "protest reported", 0.7, "grave", ""))
        )

        result = agreement.score(rows)
        assert result["floor_violations"] == 1

    def test_a_model_scoring_above_the_human_is_not_a_floor_violation(self):
        """Over-scoring is a calibration miss, not the failure this counts."""
        rows = agreement.parse_sheet(
            _sheet(_row("protest", 0.7, "grave", "unrest", 0.3, "tension", ""))
        )

        assert agreement.score(rows)["floor_violations"] == 0

    def test_both_above_the_floor_is_not_a_violation(self):
        rows = agreement.parse_sheet(
            _sheet(_row("3 killed", 0.6, "grave", "r", 0.9, "mass_casualty", ""))
        )

        assert agreement.score(rows)["floor_violations"] == 0


class TestRationaleAndError:
    def test_rationale_rate_counts_only_rows_where_the_human_judged_it(self):
        rows = agreement.parse_sheet(
            _sheet(
                _row("a", 0.6, "grave", "r", 0.6, "grave", "ok"),
                _row("b", 0.6, "grave", "softened", 0.6, "grave", "no"),
                _row("c", 0.6, "grave", "r", 0.6, "grave", ""),
            )
        )

        assert agreement.score(rows)["rationale_ok_rate"] == 0.5

    def test_mean_absolute_error_uses_only_numerically_graded_rows(self):
        rows = agreement.parse_sheet(
            _sheet(
                _row("a", 0.6, "grave", "r", 0.7, "grave", "ok"),
                _row("b", 0.2, "tension", "r", "", "tension", "ok"),
            )
        )

        assert agreement.score(rows)["mean_absolute_error"] == pytest.approx(0.1)

    def test_reports_none_rather_than_a_fake_number_when_nothing_qualifies(self):
        rows = agreement.parse_sheet(_sheet(_row("a", 0.6, "grave", "r", "", "grave", "")))

        result = agreement.score(rows)
        assert result["mean_absolute_error"] is None
        assert result["rationale_ok_rate"] is None


class TestEmpty:
    def test_an_unfilled_sheet_scores_nothing_rather_than_zero(self):
        result = agreement.score([])

        assert result["n"] == 0
        assert result["band_agreement"] is None


class TestSheet:
    """The emitted sheet has to round-trip through the parser (#593)."""

    def _row(self, headline, severity, band, rationale):
        from app.db_models import EventRow

        return EventRow(
            source="rss-test",
            source_event_id=headline,
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            category="news",
            severity=severity,
            keywords=[],
            payload={
                "title": headline,
                "severity_band": band,
                "severity_rationale": rationale,
                "severity_method": news.METHOD,
            },
        )

    def test_the_sheet_it_emits_parses_back(self):
        from app.severity import audit

        sheet = audit.build_sheet(
            [self._row("Three killed in attack", 0.6, "grave", "three killed")],
            created="2026-07-22",
        )

        # Unfilled: the parser must drop it rather than count it as agreement.
        assert agreement.parse_sheet(sheet) == []

    def test_a_filled_emitted_sheet_scores(self):
        from app.severity import audit

        sheet = audit.build_sheet(
            [self._row("Three killed in attack", 0.6, "grave", "three killed")],
            created="2026-07-22",
        )
        filled = sheet.replace("| three killed |  |  |  |", "| three killed | 0.65 | grave | ok |")

        result = agreement.score(agreement.parse_sheet(filled))
        assert result["band_agreement"] == 1.0
        assert result["floor_violations"] == 0

    def test_a_pipe_in_a_headline_cannot_break_the_table(self):
        from app.severity import audit

        sheet = audit.build_sheet(
            [self._row("Rebels | govt clash, 4 dead", 0.7, "grave", "four killed")],
            created="2026-07-22",
        )

        assert all(
            line.count("|") == 8 for line in sheet.splitlines() if line.startswith("| Rebels")
        )
