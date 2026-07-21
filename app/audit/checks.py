"""The audit rules (#580). Pure — no database, no clock of their own.

Each rule reads a SourceStats and an Expectation and either returns a Finding or
nothing. Thresholds are module constants so tuning does not mean editing rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.audit.expectations import Expectation
from app.audit.stats import SourceStats

#: A declared severity should be present on essentially every row. Not 100%:
#: a handful of malformed upstream rows is normal, a systematic gap is not.
MIN_COVERAGE = 0.99

#: Below this many distinct values, "continuous" is not an honest description.
MIN_CONTINUOUS_DISTINCT = 4

#: Above this share on a single value, neither is it — a column can have many
#: distinct values and still be a constant with noise.
MAX_CONTINUOUS_TOP_SHARE = 0.90

#: A source with nothing newer than this has gone quiet, or is republishing
#: archive content as if it were current (#571). Deliberately not the retention
#: window: FRED and EM-DAT are retention-exempt, and FRED's monthly series
#: legitimately lag by weeks.
STALE_AFTER_DAYS = 90

#: Publishers post-date by minutes and clocks drift, so a small future margin is
#: normal and flagging it would be noise. Measured live, rss-jpost-world runs
#: 1h42m ahead — past this margin, and a genuine finding.
FUTURE_TOLERANCE = timedelta(hours=1)


@dataclass(frozen=True)
class Finding:
    """One thing the audit objects to."""

    source: str
    check: str
    detail: str


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def check_no_data(stats: SourceStats, expectation: Expectation) -> Finding | None:
    """Reported, never raised: paused sources (#160, #155) legitimately have none."""
    if stats.rows:
        return None
    return Finding(stats.source, "no_data", "no rows in the events table")


def check_severity_coverage(stats: SourceStats, expectation: Expectation) -> Finding | None:
    if expectation.severity == "none":
        return None
    if stats.severity_coverage >= MIN_COVERAGE:
        return None
    return Finding(
        stats.source,
        "severity_coverage",
        f"declares severity {expectation.severity!r} but only "
        f"{stats.severity_present:,}/{stats.rows:,} rows carry one "
        f"({_pct(stats.severity_coverage)})",
    )


def check_severity_shape(stats: SourceStats, expectation: Expectation) -> Finding | None:
    """A continuous declaration against a column that is really a flag."""
    if expectation.severity != "continuous" or not stats.severity_present:
        return None
    if stats.severity_distinct < MIN_CONTINUOUS_DISTINCT:
        return Finding(
            stats.source,
            "severity_shape",
            f"declares severity continuous but takes only {stats.severity_distinct} "
            f"distinct value(s)",
        )
    if stats.severity_top_share is not None and stats.severity_top_share > MAX_CONTINUOUS_TOP_SHARE:
        return Finding(
            stats.source,
            "severity_shape",
            f"declares severity continuous but {_pct(stats.severity_top_share)} of rows "
            f"share one value",
        )
    return None


def check_severity_constant(stats: SourceStats, expectation: Expectation) -> Finding | None:
    """No declaration excuses a column with a single value on every row.

    A constant carries no information by construction, so whatever reads it is
    computing a number from nothing. OpenSky: 58,793 rows, severity 0.0.
    """
    if stats.severity_present <= 1 or stats.severity_std is None:
        return None
    if stats.severity_std > 0.0:
        return None
    return Finding(
        stats.source,
        "severity_constant",
        f"severity is the same value on all {stats.severity_present:,} rows that carry one",
    )


def check_severity_absent_but_present(
    stats: SourceStats, expectation: Expectation
) -> Finding | None:
    if expectation.severity != "none" or not stats.severity_present:
        return None
    return Finding(
        stats.source,
        "severity_absent_but_present",
        f"declares no severity but {stats.severity_present:,} rows carry one",
    )


def check_country_coverage(stats: SourceStats, expectation: Expectation) -> Finding | None:
    if expectation.country != "required":
        return None
    if stats.country_coverage >= MIN_COVERAGE:
        return None
    return Finding(
        stats.source,
        "country_coverage",
        f"declares country required but only {stats.country_present:,}/{stats.rows:,} rows "
        f"carry one ({_pct(stats.country_coverage)})",
    )


def check_composite_reachability(stats: SourceStats, expectation: Expectation) -> Finding | None:
    """Declared to feed the composite, but nothing survives its filter.

    This is the check the whole audit exists for. Every other rule inspects a
    column; this one asks whether anything downstream can actually read it.
    """
    if not expectation.feeds_composite or stats.composite_eligible:
        return None
    return Finding(
        stats.source,
        "composite_reachability",
        f"declared to feed the composite, but 0 of {stats.rows:,} rows pass its filter "
        f"(category in set, severity and country both non-null)",
    )


def check_occurred_at_plausible(
    stats: SourceStats, expectation: Expectation, *, now: datetime
) -> Finding | None:
    if stats.latest is None:
        return None
    if stats.latest > now + FUTURE_TOLERANCE:
        ahead = stats.latest - now
        return Finding(
            stats.source,
            "occurred_at_plausible",
            f"newest row is dated {stats.latest.isoformat()}, {ahead} in the future",
        )
    age = now - stats.latest
    if age > timedelta(days=STALE_AFTER_DAYS):
        return Finding(
            stats.source,
            "occurred_at_plausible",
            f"newest row is {age.days} days old — the source has gone quiet, or is "
            f"publishing archive content as current",
        )
    return None


def run_all(stats: SourceStats, expectation: Expectation, *, now: datetime) -> list[Finding]:
    """Every rule against one source. An empty list means nothing to object to.

    A source with no rows short-circuits: every other rule would fire on an
    empty table and say nothing useful.
    """
    empty = check_no_data(stats, expectation)
    if empty is not None:
        return [empty]

    findings = [
        check(stats, expectation)
        for check in (
            check_severity_coverage,
            check_severity_shape,
            check_severity_constant,
            check_severity_absent_but_present,
            check_country_coverage,
            check_composite_reachability,
        )
    ]
    findings.append(check_occurred_at_plausible(stats, expectation, now=now))
    return [finding for finding in findings if finding is not None]
