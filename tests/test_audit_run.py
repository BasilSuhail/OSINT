"""Stats assembly and whole-audit wiring (#580)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import run
from app.db_models import EventRow

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _add(
    session,
    source,
    *,
    n=1,
    severity=None,
    country="US",
    category="hazard",
    occurred=None,
    method=None,
):
    for i in range(n):
        session.add(
            EventRow(
                source=source,
                source_event_id=f"{source}-{severity}-{country}-{method}-{i}",
                occurred_at=occurred or NOW - timedelta(hours=1),
                fetched_at=NOW,
                category=category,
                severity=severity,
                country=country,
                keywords=[],
                payload={"severity_method": method} if method else {},
            )
        )
    session.commit()


def _by_source(stats):
    return {s.source: s for s in stats}


def test_counts_rows_severity_and_country(db_session):
    _add(db_session, "gdacs", n=3, severity=0.2, country="US")
    _add(db_session, "gdacs", n=1, severity=None, country=None)

    stats = _by_source(run.gather_stats(db_session))["gdacs"]

    assert (stats.rows, stats.severity_present, stats.country_present) == (4, 3, 3)


def test_measures_the_spread_of_severity(db_session):
    _add(db_session, "gdacs", n=9, severity=0.2, country="US")
    _add(db_session, "gdacs", n=1, severity=0.6, country="GB")

    stats = _by_source(run.gather_stats(db_session))["gdacs"]

    assert stats.severity_distinct == 2
    assert stats.severity_top_share == 0.9
    assert stats.severity_std is not None and stats.severity_std > 0


def test_a_constant_severity_measures_zero_spread(db_session):
    """OpenSky's shape: many rows, one value."""
    _add(db_session, "opensky-adsb", n=5, severity=0.0, country=None)

    stats = _by_source(run.gather_stats(db_session))["opensky-adsb"]

    assert (stats.severity_distinct, stats.severity_std) == (1, 0.0)


def test_rss_shape_uses_current_model_rows_but_coverage_uses_all(db_session):
    _add(
        db_session,
        "rss-example",
        n=40,
        severity=0.35,
        category="news",
        method="news-keyword-v2",
    )
    _add(
        db_session,
        "rss-example",
        n=5,
        severity=0.61,
        category="news",
        method="news-llm-v1",
    )

    stats = _by_source(run.gather_stats(db_session))["rss-example"]

    assert stats.severity_present == 45
    assert stats.severity_shape_present == 5
    assert stats.severity_distinct == 1


def test_composite_eligibility_applies_the_real_filter(db_session):
    _add(db_session, "polymarket", n=4, severity=0.5, country=None, category="market")
    _add(db_session, "yfinance", n=2, severity=0.5, country="US", category="market")
    _add(db_session, "rss-bbc-world", n=3, severity=0.35, country="US", category="news")

    stats = _by_source(run.gather_stats(db_session))

    assert stats["polymarket"].composite_eligible == 0  # country is null
    assert stats["yfinance"].composite_eligible == 2
    assert stats["rss-bbc-world"].composite_eligible == 0  # category outside the set


def test_reports_earliest_and_latest_as_aware_datetimes(db_session):
    _add(db_session, "gdacs", n=1, severity=0.2, occurred=NOW - timedelta(days=5))
    _add(db_session, "gdacs", n=1, severity=0.6, occurred=NOW - timedelta(days=1))

    stats = _by_source(run.gather_stats(db_session))["gdacs"]

    assert stats.earliest is not None and stats.earliest.tzinfo is not None
    assert (NOW - stats.earliest).days == 5
    assert (NOW - stats.latest).days == 1


def test_an_undeclared_source_is_itself_a_finding(db_session):
    """A new fetcher must not be able to enter the system unnoticed."""
    _add(db_session, "brand-new-feed", n=2, severity=0.5)

    findings = [
        finding for finding in run.audit(db_session, now=NOW) if finding.source == "brand-new-feed"
    ]

    assert [f.check for f in findings] == ["undeclared_source"]


def test_absent_core_source_is_measured_as_zero_row(db_session):
    stats = _by_source(run.gather_stats(db_session))["yfinance"]

    assert stats.rows == 0
    assert stats.state == "zero_row"
    assert {
        finding.check for finding in run.audit(db_session, now=NOW) if finding.source == "yfinance"
    } == {"no_data"}


def test_missing_core_file_does_not_silently_disable_its_schedule(db_session):
    stats = _by_source(run.gather_stats(db_session))["emdat"]

    assert stats.state == "zero_row"
    assert {
        finding.check for finding in run.audit(db_session, now=NOW) if finding.source == "emdat"
    } == {"no_data"}


def test_absent_enabled_rss_source_is_measured_as_zero_row(db_session):
    stats = _by_source(run.gather_stats(db_session))["rss-bbc-world"]

    assert stats.rows == 0
    assert stats.state == "zero_row"
    assert {
        finding.check
        for finding in run.audit(db_session, now=NOW)
        if finding.source == "rss-bbc-world"
    } == {"no_data"}


def test_disabled_rss_source_is_measured_without_a_finding(db_session):
    stats = _by_source(run.gather_stats(db_session))["rss-nhk-world"]

    assert stats.rows == 0
    assert stats.state == "disabled"
    assert [
        finding for finding in run.audit(db_session, now=NOW) if finding.source == "rss-nhk-world"
    ] == []


def test_runtime_registered_rss_source_uses_family_declaration(db_session, monkeypatch):
    monkeypatch.setattr(run, "registered_names", lambda: frozenset({"rss-runtime-test"}))

    stats = _by_source(run.gather_stats(db_session))["rss-runtime-test"]
    findings = [
        finding
        for finding in run.audit(db_session, now=NOW)
        if finding.source == "rss-runtime-test"
    ]

    assert stats.state == "zero_row"
    assert [finding.check for finding in findings] == ["no_data"]


def test_sources_measured_counts_the_complete_universe(db_session):
    findings, sources_measured = run.audit_detail(db_session, now=NOW)
    stats = run.gather_stats(db_session)

    assert findings
    assert sources_measured == len(stats)
    assert sources_measured > 0


def test_a_declared_healthy_source_produces_nothing(db_session):
    _add(db_session, "yfinance", n=200, severity=0.1, country="US", category="market")
    for i, sev in enumerate([0.2, 0.3, 0.4, 0.5, 0.6]):
        _add(db_session, "yfinance", n=20, severity=sev, country=f"G{i}", category="market")

    findings = [f for f in run.audit(db_session, now=NOW) if f.source == "yfinance"]

    assert findings == []


def test_polymarket_no_longer_claims_a_composite_role(db_session):
    """Country on no row — and since #682 it does not claim to need one.

    This used to assert `composite_reachability` fires. It did, correctly, while
    polymarket declared `feeds_composite=True` and delivered nothing. The
    declaration was the wrong half: severity there is market *uncertainty*, and
    the stored sample was 94 US primary horse-race markets and 9 World Cup
    football bets against exactly one conflict question. A 50/50 nomination race
    would have scored as maximum national stress.

    So the finding is gone because the claim is gone, not because the data
    changed. The audit is right in both versions; only the declaration moved.
    """
    _add(db_session, "polymarket", n=100, severity=0.5, country=None, category="prediction")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW) if f.source == "polymarket"}

    assert "composite_reachability" not in checks_fired


def test_fred_scoring_its_own_history_is_clean(db_session):
    """#715. This used to assert the opposite, and both were true in their turn.

    FRED emitted severity None on every row behind a comment claiming the
    composite normalised it, so composite_reachability fired and was correct.
    #684 moved the computation into the fetcher and #691 widened the panel to 27
    countries; the live table now carries 874 rows and 576 distinct severities.
    The declaration follows the data.
    """
    for i, sev in enumerate([0.1, 0.4, 0.55, 0.8, 0.95] * 8):
        _add(db_session, "fred", n=1, severity=sev + i * 1e-4, country="US", category="market")
    # A quarter carry none, as the cold-start rule guarantees they always will.
    _add(db_session, "fred", n=13, severity=None, country="US", category="market")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW) if f.source == "fred"}

    assert checks_fired == set()


def test_fred_losing_its_severity_entirely_is_still_caught(db_session):
    # The declared floor relaxes the threshold; it must not remove the check.
    _add(db_session, "fred", n=50, severity=None, country="US", category="market")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW) if f.source == "fred"}

    assert "severity_coverage" in checks_fired
    assert "composite_reachability" in checks_fired


def test_rss_sources_resolve_through_the_family_declaration(db_session):
    _add(
        db_session,
        "rss-some-new-outlet",
        n=100,
        severity=0.35,
        country="US",
        category="news",
        method="news-keyword-v2",
    )

    checks_fired = {f.check for f in run.audit(db_session, now=NOW)}

    assert "undeclared_source" not in checks_fired
    assert "severity_shape" not in checks_fired  # graded fallback is not the continuous sample
