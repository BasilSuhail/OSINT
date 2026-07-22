"""Gather per-source stats and apply the audit rules (#580).

Two grouped queries over the events table, then pure functions. Severity spread
is computed in Python from grouped value counts rather than in SQL: the counts
are bounded by distinct severities, and it keeps the arithmetic identical on
SQLite and Postgres.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.audit import checks, expectations
from app.audit.stats import SourceStats
from app.db_models import EventRow

#: The composite's own category filter, restated rather than imported.
#: Deliberate: this check must fail when the composite's filter and a source's
#: data drift apart, which it cannot do if both sides derive from one expression.
COMPOSITE_CATEGORIES = ("market", "geopolitical", "hazard")


def _severity_counts(session: Session) -> dict[str, dict[float, int]]:
    """{source: {severity_value: rows}} over rows that carry a severity."""
    rows = session.execute(
        select(EventRow.source, EventRow.severity, func.count())
        .where(EventRow.severity.isnot(None))
        .group_by(EventRow.source, EventRow.severity)
    ).all()
    counts: dict[str, dict[float, int]] = defaultdict(dict)
    for source, severity, count in rows:
        counts[source][float(severity)] = count
    return counts


def _spread(counts: dict[float, int]) -> tuple[int, float | None, float | None]:
    """(distinct, top-value share, population std) from grouped value counts.

    Top share matters as much as std: a column taking two values split evenly
    has a perfectly healthy std while still being a flag.
    """
    total = sum(counts.values())
    if not total:
        return 0, None, None
    top_share = max(counts.values()) / total
    mean = sum(value * n for value, n in counts.items()) / total
    variance = sum(n * (value - mean) ** 2 for value, n in counts.items()) / total
    return len(counts), top_share, variance**0.5


def gather_stats(session: Session) -> list[SourceStats]:
    """Measure every source present in the events table."""
    severity_counts = _severity_counts(session)

    eligible = case(
        (
            EventRow.category.in_(COMPOSITE_CATEGORIES)
            & EventRow.severity.isnot(None)
            & EventRow.country.isnot(None),
            1,
        ),
        else_=0,
    )
    rows = session.execute(
        select(
            EventRow.source,
            func.count(),
            func.count(EventRow.country),
            func.min(EventRow.occurred_at),
            func.max(EventRow.occurred_at),
            func.sum(eligible),
        ).group_by(EventRow.source)
    ).all()

    stats: list[SourceStats] = []
    for source, total, country_present, earliest, latest, composite_eligible in rows:
        counts = severity_counts.get(source, {})
        distinct, top_share, std = _spread(counts)
        stats.append(
            SourceStats(
                source=source,
                rows=total,
                severity_present=sum(counts.values()),
                severity_distinct=distinct,
                severity_top_share=top_share,
                severity_std=std,
                country_present=country_present,
                earliest=_as_utc(earliest),
                latest=_as_utc(latest),
                composite_eligible=int(composite_eligible or 0),
            )
        )
    stats.sort(key=lambda s: s.source)
    return stats


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres hands back aware ones."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def audit(session: Session, *, now: datetime | None = None) -> list[checks.Finding]:
    """Every finding across every source, plus any source nothing declares."""
    moment = now or datetime.now(UTC)
    findings: list[checks.Finding] = []
    for stats in gather_stats(session):
        expectation = expectations.for_source(stats.source)
        if expectation is None:
            findings.append(
                checks.Finding(
                    stats.source,
                    "undeclared_source",
                    f"{stats.rows:,} rows, but no expectation declares what this source "
                    f"should produce",
                )
            )
            continue
        findings.extend(checks.run_all(stats, expectation, now=moment))
    return findings
