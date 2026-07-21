"""Stats assembly and whole-audit wiring (#580)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.audit import run
from app.db_models import EventRow

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _add(session, source, *, n=1, severity=None, country="US", category="hazard", occurred=None):
    for i in range(n):
        session.add(
            EventRow(
                source=source,
                source_event_id=f"{source}-{severity}-{country}-{i}",
                occurred_at=occurred or NOW - timedelta(hours=1),
                fetched_at=NOW,
                category=category,
                severity=severity,
                country=country,
                keywords=[],
                payload={},
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

    findings = run.audit(db_session, now=NOW)

    assert [f.check for f in findings] == ["undeclared_source"]


def test_a_declared_healthy_source_produces_nothing(db_session):
    _add(db_session, "yfinance", n=200, severity=0.1, country="US", category="market")
    for i, sev in enumerate([0.2, 0.3, 0.4, 0.5, 0.6]):
        _add(db_session, "yfinance", n=20, severity=sev, country=f"G{i}", category="market")

    findings = [f for f in run.audit(db_session, now=NOW) if f.source == "yfinance"]

    assert findings == []


def test_the_polymarket_shape_is_caught_end_to_end(db_session):
    """Severity on every row, country on none, so the composite reads nothing."""
    _add(db_session, "polymarket", n=100, severity=0.5, country=None, category="market")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW) if f.source == "polymarket"}

    assert "composite_reachability" in checks_fired


def test_the_fred_shape_is_caught_end_to_end(db_session):
    """Declared severity none, and the composite therefore cannot read it."""
    _add(db_session, "fred", n=50, severity=None, country="US", category="market")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW) if f.source == "fred"}

    assert checks_fired == {"composite_reachability"}


def test_rss_sources_resolve_through_the_family_declaration(db_session):
    _add(db_session, "rss-some-new-outlet", n=10, severity=0.35, country="US", category="news")

    checks_fired = {f.check for f in run.audit(db_session, now=NOW)}

    assert "undeclared_source" not in checks_fired
    assert "severity_shape" in checks_fired  # one distinct value, declared continuous
