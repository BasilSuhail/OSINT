"""The per-source audit rules (#580).

`checks` is pure — every rule runs against a constructed SourceStats, so the
whole rule set is testable without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import checks
from app.audit.expectations import Expectation
from app.audit.stats import SourceStats

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _stats(**overrides) -> SourceStats:
    """A source that passes every check, so each test perturbs one thing."""
    base = {
        "source": "example",
        "rows": 1000,
        "severity_present": 1000,
        "severity_distinct": 40,
        "severity_top_share": 0.10,
        "severity_std": 0.25,
        "country_present": 1000,
        "earliest": NOW - timedelta(days=10),
        "latest": NOW - timedelta(hours=1),
        "composite_eligible": 1000,
    }
    return SourceStats(**{**base, **overrides})


CONTINUOUS = Expectation(severity="continuous", country="required", feeds_composite=True)


def _names(findings) -> set[str]:
    return {f.check for f in findings}


def test_a_healthy_source_produces_no_findings():
    assert checks.run_all(_stats(), CONTINUOUS, now=NOW) == []


def test_declared_severity_that_is_mostly_null_is_a_finding():
    """FRED: 287 rows, severity None on every one."""
    findings = checks.run_all(_stats(severity_present=0), CONTINUOUS, now=NOW)

    assert "severity_coverage" in _names(findings)


def test_partial_severity_coverage_is_a_finding():
    """FIRMS before #577: 13.7%."""
    findings = checks.run_all(_stats(severity_present=137), CONTINUOUS, now=NOW)

    assert "severity_coverage" in _names(findings)


def test_declared_continuous_but_only_two_values_is_a_finding():
    """Every RSS row in the system is 0.35 or 0.65."""
    findings = checks.run_all(
        _stats(severity_distinct=2, severity_top_share=0.68, severity_std=0.14),
        CONTINUOUS,
        now=NOW,
    )

    assert "severity_shape" in _names(findings)


def test_declared_continuous_but_one_value_dominates_is_a_finding():
    """GDACS: 606 of 616 rows at 0.2."""
    findings = checks.run_all(
        _stats(severity_distinct=3, severity_top_share=0.984), CONTINUOUS, now=NOW
    )

    assert "severity_shape" in _names(findings)


def test_a_graded_declaration_accepts_a_coarse_scale():
    """Three alert levels are a legitimate design, once declared."""
    graded = Expectation(severity="graded", country="required", feeds_composite=True)

    findings = checks.run_all(
        _stats(severity_distinct=3, severity_top_share=0.984), graded, now=NOW
    )

    assert "severity_shape" not in _names(findings)


def test_a_constant_severity_is_a_finding_even_when_graded():
    """OpenSky: 58,793 rows, severity 0.0 on every one. No declaration excuses that."""
    graded = Expectation(severity="graded", country="optional", feeds_composite=False)

    findings = checks.run_all(
        _stats(severity_distinct=1, severity_top_share=1.0, severity_std=0.0),
        graded,
        now=NOW,
    )

    assert "severity_constant" in _names(findings)


def test_severity_declared_absent_but_present_is_a_finding():
    absent = Expectation(severity="none", country="optional", feeds_composite=False)

    findings = checks.run_all(_stats(severity_present=1000), absent, now=NOW)

    assert "severity_absent_but_present" in _names(findings)


def test_severity_declared_absent_and_absent_is_clean():
    absent = Expectation(severity="none", country="optional", feeds_composite=False)

    findings = checks.run_all(
        _stats(
            severity_present=0,
            severity_distinct=0,
            severity_top_share=None,
            severity_std=None,
            composite_eligible=0,
        ),
        absent,
        now=NOW,
    )

    assert _names(findings) == set()


def test_missing_country_when_required_is_a_finding():
    findings = checks.run_all(_stats(country_present=0), CONTINUOUS, now=NOW)

    assert "country_coverage" in _names(findings)


def test_a_source_that_feeds_the_composite_but_reaches_none_of_it_is_a_finding():
    """Polymarket: severity on all 109 rows, country on none, so the composite drops all."""
    findings = checks.run_all(_stats(composite_eligible=0), CONTINUOUS, now=NOW)

    assert "composite_reachability" in _names(findings)


def test_reachability_is_not_checked_for_sources_that_do_not_feed_the_composite():
    outside = Expectation(severity="continuous", country="optional", feeds_composite=False)

    findings = checks.run_all(_stats(composite_eligible=0), outside, now=NOW)

    assert "composite_reachability" not in _names(findings)


def test_future_dated_rows_are_a_finding():
    findings = checks.run_all(_stats(latest=NOW + timedelta(days=2)), CONTINUOUS, now=NOW)

    assert "occurred_at_plausible" in _names(findings)


def test_a_few_minutes_into_the_future_is_tolerated():
    """Publishers post-date and clocks drift; flagging that would be noise."""
    findings = checks.run_all(_stats(latest=NOW + timedelta(minutes=5)), CONTINUOUS, now=NOW)

    assert "occurred_at_plausible" not in _names(findings)


def test_a_source_whose_newest_row_predates_retention_is_a_finding():
    """The #571 shape: a feed republishing 2021 content, or one that has gone quiet."""
    findings = checks.run_all(
        _stats(
            earliest=NOW - timedelta(days=400),
            latest=NOW - timedelta(days=365),
        ),
        CONTINUOUS,
        now=NOW,
    )

    assert "occurred_at_plausible" in _names(findings)


def test_a_source_with_no_rows_reports_no_data_and_nothing_else():
    """Paused sources (#160, #155) legitimately have none — not an error."""
    findings = checks.run_all(
        _stats(
            rows=0,
            severity_present=0,
            severity_distinct=0,
            severity_top_share=None,
            severity_std=None,
            country_present=0,
            earliest=None,
            latest=None,
            composite_eligible=0,
        ),
        CONTINUOUS,
        now=NOW,
    )

    assert _names(findings) == {"no_data"}


def test_findings_name_the_source_and_carry_detail():
    findings = checks.run_all(_stats(source="fred", severity_present=0), CONTINUOUS, now=NOW)

    finding = next(f for f in findings if f.check == "severity_coverage")
    assert finding.source == "fred"
    assert finding.detail
