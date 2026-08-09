"""Can this console be trusted right now? (#828)

Every part of the answer already existed and nothing assembled it, so
answering it meant running four probes by hand and reading a Postgres table.

The questions are the ones this project keeps learning the hard way, each with
the incident that taught it:

- **What is silent?** UK Police reported four successful fetch days out of six
  while storing zero rows (#765). GDELT was parked for three hours over a file
  published two minutes late (#808). Both looked healthy from every angle
  except the one that counted.
- **What is drawn that should not be?** 181 of 31,361 positioned rows stood on
  a place somebody verified; the rest were centroids drawn identically (#773).
- **What is this corpus made of?** GDELT is 69.6% of what the world-status
  panel counts and news is 28.2%, so "the loudest country" is a fact about
  GDELT's coverage wearing a world label.
- **How old is the freshest thing here?** Per class, because a live wire and a
  monthly crime archive are both healthy at very different ages.

## Two decisions worth stating

**No overall score.** A single number would hide the thing this exists to
show: the system is strong on some of these and blind on others, and an
average of the two is never wrong and never useful.

**Nothing is measured twice.** Every figure comes from the module that already
owns it — `watchdog` for silence, `source_quarantine` for rest, the stored
audit run for findings, `location_precision` for what a coordinate claims. A
second implementation of any of these would drift, and then two screens would
disagree about whether the system is working.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db_models import (
    AuditFindingRow,
    AuditRunRow,
    EventRow,
    IngestHealthRow,
    SourceQuarantineRow,
)
from app.location_precision import precision_of

#: How a source is grouped for composition and freshness. A wire, a machine
#: coder, an instrument and an indicator feed age differently and are worth
#: believing differently, so they are never summed into one number.
SOURCE_CLASSES: Final[dict[str, tuple[str, ...]]] = {
    "news": ("rss-",),
    "machine-coded": ("gdelt", "acled"),
    "hazard": ("usgs-quake", "gdacs", "eonet", "nasa-firms"),
    "aviation": ("opensky-adsb",),
    "cyber": ("abuse-ch-",),
    "market": ("yfinance", "fred", "polymarket"),
    "crime": ("uk-police",),
}

#: Rows newer than this are "recent" for composition and precision. Long
#: enough that a daily feed appears, short enough that a source which died
#: yesterday does not look alive.
RECENT_WINDOW: Final[timedelta] = timedelta(days=7)

#: A precision sample large enough to be stable and small enough to be free.
PRECISION_SAMPLE: Final[int] = 2000


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def class_of(source: str) -> str:
    """Which class a source belongs to, or `other` when nothing claims it.

    `other` is deliberately visible rather than folded into a neighbour: a
    source no class knows about is a source nobody decided how to read.
    """
    for name, prefixes in SOURCE_CLASSES.items():
        for prefix in prefixes:
            if source == prefix or (prefix.endswith("-") and source.startswith(prefix)):
                return name
    return "other"


@dataclass
class SilentSource:
    source: str
    #: None when the source has never succeeded. Distinct from a large number
    #: on purpose: "we have never heard from this" and "we last heard from
    #: this two days ago" are different problems with different fixes.
    minutes_silent: int | None
    cadence_minutes: int


@dataclass
class RestedSource:
    source: str
    kind: str
    http_status: int | None
    retry_after: str
    detail: str


@dataclass
class OutputIssue:
    source: str
    state: str
    last_checked: str | None
    last_output: str | None
    fetched: int
    accepted: int
    inserted: int
    rejected: int


@dataclass
class ClassHealth:
    name: str
    rows: int
    share: float
    newest_age_minutes: int | None
    sources: int


@dataclass
class ConsoleHealth:
    generated_at: str
    silent: list[SilentSource] = field(default_factory=list)
    rested: list[RestedSource] = field(default_factory=list)
    output_health: list[OutputIssue] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
    composition: list[ClassHealth] = field(default_factory=list)
    precision: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _silent(session: Session, now: datetime) -> list[SilentSource]:
    """Sources past their own cadence, from the watchdog that already decides."""
    from app.watchdog import SOURCE_CADENCE_MIN, check_sources

    out: list[SilentSource] = []
    for source, state in check_sources(session, now=now).items():
        if not state.get("is_stale"):
            continue
        last = (
            state.get("last_output")
            if state.get("freshness_basis") == "output"
            else state.get("last_success")
        )
        minutes = (
            int((now - _as_utc(last)).total_seconds() / 60) if isinstance(last, datetime) else None
        )
        out.append(
            SilentSource(
                source=source,
                minutes_silent=minutes,
                cadence_minutes=int(SOURCE_CADENCE_MIN.get(source, 0)),
            )
        )
    #: Never-heard-from first, then longest silence. Both are worse than a
    #: source that missed one cycle, and a list ordered by severity is the
    #: only kind anyone reads to the bottom of.
    return sorted(out, key=lambda s: (s.minutes_silent is not None, -(s.minutes_silent or 0)))


def _rested(session: Session) -> list[RestedSource]:
    rows = session.execute(
        select(SourceQuarantineRow).order_by(SourceQuarantineRow.retry_after)
    ).scalars()
    return [
        RestedSource(
            source=row.source,
            kind=row.kind,
            http_status=row.http_status,
            retry_after=row.retry_after.isoformat(),
            detail=(row.detail or "")[:140],
        )
        for row in rows
    ]


def _output_health(session: Session) -> list[OutputIssue]:
    """Latest explicit non-healthy output state for each measured source."""
    latest = (
        select(IngestHealthRow.source, func.max(IngestHealthRow.day).label("day"))
        .group_by(IngestHealthRow.source)
        .subquery()
    )
    output_clock = (
        select(
            IngestHealthRow.source,
            func.max(IngestHealthRow.last_output).label("last_output"),
        )
        .group_by(IngestHealthRow.source)
        .subquery()
    )
    rows = session.execute(
        select(IngestHealthRow, output_clock.c.last_output)
        .join(
            latest,
            and_(
                latest.c.source == IngestHealthRow.source,
                latest.c.day == IngestHealthRow.day,
            ),
        )
        .join(output_clock, output_clock.c.source == IngestHealthRow.source)
        .where(IngestHealthRow.last_state.in_(("empty", "misconfigured", "failed")))
        .order_by(IngestHealthRow.source)
    ).all()
    return [
        OutputIssue(
            source=health.source,
            state=str(health.last_state),
            last_checked=health.last_checked.isoformat() if health.last_checked else None,
            last_output=last_output.isoformat() if last_output else None,
            fetched=int(health.last_fetched or 0),
            accepted=int(health.last_accepted or 0),
            inserted=int(health.last_inserted or 0),
            rejected=int(health.last_rejected or 0),
        )
        for health, last_output in rows
    ]


def _audit(session: Session) -> dict[str, Any]:
    """The last stored audit, not a fresh one.

    Recomputing on every panel load would put two grouped queries over the
    whole events table behind a page render. The nightly run is the measure;
    this reports it, and says when it ran so a stale one is visible as stale
    rather than as clean.
    """
    run = (
        session.execute(select(AuditRunRow).order_by(AuditRunRow.started_at.desc()))
        .scalars()
        .first()
    )
    if run is None:
        return {"ran_at": None, "findings_total": 0, "by_check": {}, "sources_measured": 0}
    rows = session.execute(
        select(AuditFindingRow.check_name, func.count())
        .where(AuditFindingRow.run_id == run.id)
        .group_by(AuditFindingRow.check_name)
    ).all()
    return {
        "ran_at": run.started_at.isoformat(),
        "findings_total": int(run.findings_total or 0),
        "sources_measured": int(run.sources_measured or 0),
        "by_check": {name: int(count) for name, count in sorted(rows, key=lambda r: -r[1])},
    }


def _composition(session: Session, now: datetime) -> list[ClassHealth]:
    """What arrived recently, and how old the newest of it is.

    Counted on **arrival**, not on occurrence. A monthly crime archive
    ingested this morning carries rows dated two months back, so an
    occurrence window reports it as contributing nothing — which is the exact
    mistake that let UK Police look healthy while storing nothing (#765),
    repeated one layer up. Freshness stays on occurrence, because that is the
    question a reader is asking: how recent is the newest thing here.
    """
    cutoff = now - RECENT_WINDOW
    rows = session.execute(
        select(EventRow.source, func.count(), func.max(EventRow.occurred_at))
        .where(EventRow.fetched_at >= cutoff)
        .group_by(EventRow.source)
    ).all()

    totals: dict[str, list[Any]] = {}
    for source, count, newest in rows:
        entry = totals.setdefault(class_of(source), [0, None, 0])
        entry[0] += int(count)
        if newest is not None:
            newest = newest if newest.tzinfo else newest.replace(tzinfo=UTC)
            entry[1] = newest if entry[1] is None else max(entry[1], newest)
        entry[2] += 1

    grand = sum(entry[0] for entry in totals.values()) or 1
    return sorted(
        (
            ClassHealth(
                name=name,
                rows=entry[0],
                share=round(entry[0] / grand, 4),
                newest_age_minutes=(
                    int((now - entry[1]).total_seconds() / 60) if entry[1] is not None else None
                ),
                sources=entry[2],
            )
            for name, entry in totals.items()
        ),
        key=lambda c: -c.rows,
    )


def _precision(session: Session, now: datetime) -> dict[str, int]:
    """What the newest positioned rows are actually claiming.

    A sample rather than the whole window: the shape of this mix moves slowly,
    and a full scan behind a page load would be paid on every refresh.
    """
    rows = session.execute(
        select(EventRow.source, EventRow.payload)
        .where(
            EventRow.occurred_at >= now - RECENT_WINDOW,
            EventRow.lat.is_not(None),
            EventRow.lon.is_not(None),
        )
        .order_by(EventRow.occurred_at.desc())
        .limit(PRECISION_SAMPLE)
    ).all()
    counts: dict[str, int] = {}
    for source, payload in rows:
        verdict = precision_of(source, payload, positioned=True)
        counts[verdict] = counts.get(verdict, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def build(session: Session, *, now: datetime | None = None) -> ConsoleHealth:
    """Assemble every existing measure into one answer."""
    moment = now or datetime.now(UTC)
    return ConsoleHealth(
        generated_at=moment.isoformat(),
        silent=_silent(session, moment),
        rested=_rested(session),
        output_health=_output_health(session),
        audit=_audit(session),
        composition=_composition(session, moment),
        precision=_precision(session, moment),
    )
