"""The per-source audit rules (#580).

`checks` is pure — every rule runs against a constructed SourceStats, so the
whole rule set is testable without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import checks
from app.audit.expectations import Expectation, for_source
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


def test_a_declared_coverage_floor_is_respected():
    """FRED (#715): its first observations legitimately carry no severity.

    `_series_to_events` emits None until a series has MIN_HISTORY + 1 points to
    judge against, and the fetcher re-reads a rolling window, so roughly a
    quarter of its rows are permanently unscored by design. Measured live: 635
    of 874. Holding it to the 99% default would report a defect that is really
    the cold-start rule working.
    """
    lenient = Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        severity_coverage_floor=0.70,
    )
    findings = checks.run_all(_stats(severity_present=727), lenient, now=NOW)

    assert "severity_coverage" not in _names(findings)


def test_a_declared_floor_still_catches_a_source_that_falls_below_it():
    # The check has to stay able to fail, or the floor is just a mute button.
    lenient = Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        severity_coverage_floor=0.70,
    )
    findings = checks.run_all(_stats(severity_present=500), lenient, now=NOW)

    assert "severity_coverage" in _names(findings)


def test_sources_without_a_declared_floor_keep_the_strict_default():
    # One source relaxing its floor must not relax everyone else's.
    findings = checks.run_all(_stats(severity_present=900), CONTINUOUS, now=NOW)

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


def test_tiny_continuous_sample_waits_for_more_evidence():
    findings = checks.run_all(
        _stats(
            severity_present=6,
            severity_shape_present=6,
            severity_distinct=1,
            severity_top_share=1.0,
            severity_std=0.0,
        ),
        CONTINUOUS,
        now=NOW,
    )

    assert "severity_shape" not in _names(findings)
    assert "severity_constant" not in _names(findings)


def test_shape_check_starts_at_the_minimum_sample():
    findings = checks.run_all(
        _stats(
            severity_present=30,
            severity_shape_present=30,
            severity_distinct=1,
            severity_top_share=1.0,
            severity_std=0.0,
        ),
        CONTINUOUS,
        now=NOW,
    )

    assert "severity_shape" in _names(findings)
    assert "severity_constant" in _names(findings)


def test_a_graded_declaration_accepts_a_coarse_scale():
    """Three alert levels are a legitimate design, once declared."""
    graded = Expectation(severity="graded", country="required", feeds_composite=True)

    findings = checks.run_all(
        _stats(severity_distinct=3, severity_top_share=0.984), graded, now=NOW
    )

    assert "severity_shape" not in _names(findings)


def test_uk_police_contract_accepts_its_intentional_category_scale():
    expectation = for_source("uk-police")
    assert expectation is not None
    assert expectation.severity == "graded"
    assert expectation.feeds_composite is False

    findings = checks.run_all(
        _stats(
            source="uk-police",
            rows=10_504,
            severity_present=10_504,
            severity_distinct=8,
            severity_top_share=0.358,
            severity_std=0.17,
            country_present=10_504,
            composite_eligible=0,
        ),
        expectation,
        now=NOW,
    )

    assert "severity_absent_but_present" not in _names(findings)
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


def test_rss_family_reports_missing_country_coverage():
    """Below the family floor, not below perfection (#827).

    680 of 1,000 was a finding when the bar was 0.99. It is the measured
    median for a healthy news feed, so the number that means "this feed has
    stopped resolving" had to move: 300 of 1,000 is out of family with every
    peer, and that is what a finding should mean.
    """
    expectation = for_source("rss-example")
    assert expectation is not None

    healthy = checks.run_all(
        _stats(source="rss-example", country_present=680), expectation, now=NOW
    )
    assert "country_coverage" not in _names(healthy)

    broken = checks.run_all(_stats(source="rss-example", country_present=300), expectation, now=NOW)
    assert "country_coverage" in _names(broken)


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
    """An active source with no rows must not disappear from the audit."""
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


def test_a_disabled_source_with_no_rows_is_clean():
    disabled = Expectation(
        severity="continuous",
        country="required",
        feeds_composite=True,
        enabled=False,
    )

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
            state="disabled",
        ),
        disabled,
        now=NOW,
    )

    assert findings == []


def test_a_disabled_source_with_rows_still_gets_semantic_checks():
    disabled = Expectation(
        severity="continuous",
        country="required",
        feeds_composite=False,
        enabled=False,
    )

    findings = checks.run_all(
        _stats(severity_present=0),
        disabled,
        now=NOW,
    )

    assert "severity_coverage" in _names(findings)


def test_a_disabled_source_is_exempt_from_staleness_but_not_future_dates():
    disabled = Expectation(
        severity="continuous",
        country="required",
        feeds_composite=False,
        enabled=False,
    )

    stale = checks.run_all(
        _stats(latest=NOW - timedelta(days=365)),
        disabled,
        now=NOW,
    )
    future = checks.run_all(
        _stats(latest=NOW + timedelta(days=2)),
        disabled,
        now=NOW,
    )

    assert "occurred_at_plausible" not in _names(stale)
    assert "occurred_at_plausible" in _names(future)


def test_findings_name_the_source_and_carry_detail():
    findings = checks.run_all(_stats(source="fred", severity_present=0), CONTINUOUS, now=NOW)

    finding = next(f for f in findings if f.check == "severity_coverage")
    assert finding.source == "fred"
    assert finding.detail
