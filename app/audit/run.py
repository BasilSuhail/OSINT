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
from app.enrichment.place import PLACE_EVIDENCE_FIELD
from app.severity import news

#: The composite's own category filter, restated rather than imported.
#: Deliberate: this check must fail when the composite's filter and a source's
#: data drift apart, which it cannot do if both sides derive from one expression.
COMPOSITE_CATEGORIES = ("market", "geopolitical", "hazard")


def _severity_counts(
    session: Session,
) -> tuple[dict[str, dict[float, int]], dict[str, dict[float, int]]]:
    """Coverage and shape counts over rows carrying severity.

    RSS ingestion always writes a graded keyword fallback. Coverage must count
    it, but a continuous-shape claim describes the later model protocol only.
    Non-RSS sources use every severity for both profiles.
    """
    method = EventRow.payload["severity_method"].as_string()
    rows = session.execute(
        select(EventRow.source, EventRow.severity, method, func.count())
        .where(EventRow.severity.isnot(None))
        .group_by(EventRow.source, EventRow.severity, method)
    ).all()
    coverage: dict[str, dict[float, int]] = defaultdict(lambda: defaultdict(int))
    shape: dict[str, dict[float, int]] = defaultdict(lambda: defaultdict(int))
    for source, severity, severity_method, count in rows:
        value = float(severity)
        coverage[source][value] += count
        if not source.startswith("rss-") or severity_method == news.METHOD:
            shape[source][value] += count
    return (
        {source: dict(counts) for source, counts in coverage.items()},
        {source: dict(counts) for source, counts in shape.items()},
    )


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
    severity_counts, shape_counts = _severity_counts(session)

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
        shape = shape_counts.get(source, {})
        distinct, top_share, std = _spread(shape)
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
                severity_shape_present=sum(shape.values()),
            )
        )
    stats.sort(key=lambda s: s.source)
    return stats


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres hands back aware ones."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _unbacked_place_rows(session: Session) -> dict[str, int]:
    """{source: rows} claiming `geo_basis='place'` with no verified location.

    Evaluated in Python over the place-basis rows only: the JSON array test
    differs between SQLite and Postgres, the set is small (hundreds), and one
    expression that works on both beats two that drift.
    """
    basis = EventRow.payload["geo_basis"].as_string()
    rows = session.execute(select(EventRow.source, EventRow.payload).where(basis == "place")).all()
    counts: dict[str, int] = defaultdict(int)
    for source, payload in rows:
        locations = (payload or {}).get(PLACE_EVIDENCE_FIELD)
        if not isinstance(locations, list) or not locations:
            counts[source] += 1
    return dict(counts)


def audit_detail(
    session: Session, *, now: datetime | None = None
) -> tuple[list[checks.Finding], int]:
    """Findings, plus how many sources were measured to produce them.

    The count cannot be derived from the findings: a source with nothing wrong
    contributes zero findings and still has to count as measured, or a clean
    night looks like a night the audit never ran.
    """
    moment = now or datetime.now(UTC)
    stats = gather_stats(session)
    findings: list[checks.Finding] = []
    for source_stats in stats:
        expectation = expectations.for_source(source_stats.source)
        if expectation is None:
            findings.append(
                checks.Finding(
                    source_stats.source,
                    "undeclared_source",
                    f"{source_stats.rows:,} rows, but no expectation declares what this "
                    f"source should produce",
                )
            )
            continue
        findings.extend(checks.run_all(source_stats, expectation, now=moment))

    # Table-wide rather than per-source: the invariant is about what a row may
    # claim, and a source with no place rows has nothing to answer for (#756).
    for source, unbacked in sorted(_unbacked_place_rows(session).items()):
        finding = checks.check_place_evidence(source, unbacked)
        if finding is not None:
            findings.append(finding)
    return findings, len(stats)


def audit(session: Session, *, now: datetime | None = None) -> list[checks.Finding]:
    """Every finding across every source, plus any source nothing declares."""
    return audit_detail(session, now=now)[0]
