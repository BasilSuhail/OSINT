"""Nightly source-data audit: record, diff, notify (#669).

`app.audit.run` measures. This records what it measured and says something only
when the answer changed. The rules themselves are untouched.

The split matters: there are ~50 standing findings. A check that pushes all of
them every night is noise by the second morning, and a muted channel is worse
than no channel — it is a channel everyone believes is working.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.checks import Finding
from app.audit.run import audit_detail
from app.db_models import AuditFindingRow, AuditRunRow
from app.watchdog import _persist_notification, _pushover_send

#: How many new findings a push names before it summarises the rest. Pushover
#: truncates around 1024 characters and 50 new findings would blow past it; the
#: full list is in `audit_findings` either way.
MAX_NAMED = 5

#: Pushover's message ceiling. Asserted against in tests rather than trusted.
PUSHOVER_MAX_CHARS = 1024


def finding_keys(findings: Iterable[Finding]) -> set[tuple[str, str]]:
    """The identity of a finding for diffing: which rule objects to which source.

    `detail` is deliberately excluded. It carries live row counts, so including
    it would make every finding "new" every night as those counts move.
    """
    return {(f.source, f.check) for f in findings}


def new_findings(previous: set[tuple[str, str]], current: Sequence[Finding]) -> list[Finding]:
    """Findings present now and absent from the previous completed run."""
    return [f for f in current if (f.source, f.check) not in previous]


def format_message(
    new: Sequence[Finding],
    *,
    baseline: bool,
    findings_total: int,
    sources_measured: int,
) -> str:
    """The push text. Baseline states the position; every later run states the change."""
    if baseline:
        return f"data audit baseline: {findings_total} findings across {sources_measured} sources"
    named = " · ".join(f"{f.source} {f.check}" for f in new[:MAX_NAMED])
    message = f"{len(new)} new audit findings: {named}"
    if len(new) > MAX_NAMED:
        message = f"{message} … +{len(new) - MAX_NAMED} more"
    return message


def _last_completed_keys(session: Session) -> set[tuple[str, str]] | None:
    """Findings of the most recent run that finished. None if there is no such run.

    "Completed" rather than "most recent" is load-bearing: a run that crashed
    part-way never reached most sources, and diffing against it would report
    everything it missed as new.
    """
    run_id = (
        session.execute(
            select(AuditRunRow.id)
            .where(AuditRunRow.finished_at.is_not(None))
            .order_by(AuditRunRow.started_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if run_id is None:
        return None
    rows = session.execute(
        select(AuditFindingRow.source, AuditFindingRow.check_name).where(
            AuditFindingRow.run_id == run_id
        )
    ).all()
    return {(source, check) for source, check in rows}


def run_audit(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Measure, record, and say something only if the answer changed."""
    moment = now or datetime.now(UTC)
    previous = _last_completed_keys(session)
    findings, sources_measured = audit_detail(session, now=moment)
    finished = datetime.now(UTC)

    run = AuditRunRow(
        started_at=moment,
        finished_at=finished,
        sources_measured=sources_measured,
        findings_total=len(findings),
    )
    session.add(run)
    session.flush()
    for finding in findings:
        session.add(
            AuditFindingRow(
                run_id=run.id,
                source=finding.source,
                check_name=finding.check,
                detail=finding.detail,
            )
        )

    baseline = previous is None
    new = findings if baseline else new_findings(previous, findings)

    pushed = 0
    if new:
        message = format_message(
            new,
            baseline=baseline,
            findings_total=len(findings),
            sources_measured=sources_measured,
        )
        # Findings are already staged above, so a dead notification channel
        # never costs history.
        if _persist_notification(
            session, source="data-audit", message=message, today=moment.date(), kind="audit"
        ):
            _pushover_send(message)
            pushed = 1

    session.flush()
    return {
        "sources": sources_measured,
        "findings": len(findings),
        "new": len(new),
        "pushed": pushed,
    }


def run_audit_job() -> dict[str, int]:
    """One nightly sweep, wrapped in the heavy-job lifecycle.

    Through `job_run` rather than called directly: `gather_stats` issues two
    full GROUP BY scans over the events table — 1,290,963 rows and 1151 MB
    measured on 2026-07-29 — which is squarely in the class of job that has to
    let the brain step aside first (#413), and which belongs on the activity
    monitor while it runs.
    """
    from sqlalchemy.orm import sessionmaker

    from app.db import get_engine
    from app.jobs.heartbeat import job_run

    engine = get_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with job_run("data-audit", session_factory=factory), Session(engine) as session:
        result = run_audit(session)
        session.commit()
    return result


if __name__ == "__main__":  # pragma: no cover - CLI entry
    print(run_audit_job())
