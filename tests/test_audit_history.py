"""Nightly source-data audit history (#669).

#580 built the only check that asks what the data *means*. It ran once. This
covers the machinery that gives it a clock and a memory — and, as hard as
anything else, the cases where it must stay silent. A guardrail that pages on
the 50 standing findings every morning is a guardrail nobody reads by Friday.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.checks import Finding
from app.audit.task import (
    MAX_NAMED,
    PUSHOVER_MAX_CHARS,
    finding_keys,
    format_message,
    new_findings,
    run_audit,
)
from app.db_models import AuditFindingRow, AuditRunRow, NotificationRow

NOW = datetime(2026, 7, 29, 3, 40, tzinfo=UTC)


def test_findings_declare_a_cascade_to_their_run() -> None:
    """A run's findings are meaningless without the run, so the FK cascades.

    Asserted declaratively: sqlite does not enforce foreign keys unless
    PRAGMA foreign_keys is ON, which the test fixture does not set. Postgres
    enforces it in production.
    """
    fk = next(iter(AuditFindingRow.__table__.c.run_id.foreign_keys))
    assert fk.column.table.name == "audit_runs"
    assert fk.ondelete == "CASCADE"


def _finding(source: str, check: str, detail: str = "detail") -> Finding:
    return Finding(source, check, detail)


def test_new_findings_returns_only_unseen_pairs() -> None:
    previous = {("opensky-adsb", "severity_constant"), ("gdacs", "severity_shape")}
    current = [
        _finding("opensky-adsb", "severity_constant"),
        _finding("gdacs", "severity_shape"),
        _finding("nasa-firms", "severity_constant"),
    ]

    assert new_findings(previous, current) == [_finding("nasa-firms", "severity_constant")]


def test_detail_change_alone_is_not_new() -> None:
    previous = finding_keys([_finding("opensky-adsb", "severity_constant", "58,793 rows")])
    current = [_finding("opensky-adsb", "severity_constant", "61,204 rows")]

    assert new_findings(previous, current) == []


def test_baseline_message_names_the_totals_not_the_findings() -> None:
    message = format_message(
        [_finding("a", "b")], baseline=True, findings_total=50, sources_measured=47
    )

    assert message == "data audit baseline: 50 findings across 47 sources"


def test_message_names_each_new_finding() -> None:
    message = format_message(
        [_finding("nasa-firms", "severity_constant"), _finding("rss-x", "country_coverage")],
        baseline=False,
        findings_total=52,
        sources_measured=47,
    )

    assert message == (
        "2 new audit findings: nasa-firms severity_constant · rss-x country_coverage"
    )


def test_message_truncates_past_five_and_stays_under_the_push_limit() -> None:
    many = [_finding(f"source-{i:02d}", "severity_constant") for i in range(50)]

    message = format_message(many, baseline=False, findings_total=90, sources_measured=47)

    assert message.startswith("50 new audit findings: ")
    assert message.count("·") == MAX_NAMED - 1
    assert message.endswith(f"… +{50 - MAX_NAMED} more")
    assert len(message) < PUSHOVER_MAX_CHARS


def _completed_run(
    session: Session,
    *,
    when: datetime,
    findings: list[tuple[str, str]],
    finished: bool = True,
) -> AuditRunRow:
    run = AuditRunRow(
        started_at=when,
        finished_at=when if finished else None,
        sources_measured=47,
        findings_total=len(findings),
    )
    session.add(run)
    session.flush()
    for source, check in findings:
        session.add(
            AuditFindingRow(run_id=run.id, source=source, check_name=check, detail="detail")
        )
    session.flush()
    return run


def _patch_audit(findings: list[Finding], sources: int = 47):
    return patch("app.audit.task.audit_detail", return_value=(findings, sources))


def _notifications(session: Session) -> list[str]:
    return list(session.execute(select(NotificationRow.message)).scalars().all())


def test_first_run_writes_baseline_and_pushes_once(db_session: Session) -> None:
    findings = [_finding(f"source-{i}", "severity_constant") for i in range(50)]

    with _patch_audit(findings), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    assert result == {"sources": 47, "findings": 50, "new": 50, "pushed": 1}
    assert len(db_session.execute(select(AuditFindingRow)).scalars().all()) == 50
    messages = _notifications(db_session)
    assert messages == ["data audit baseline: 50 findings across 47 sources"]
    push.assert_called_once()


def test_unchanged_second_run_pushes_nothing(db_session: Session) -> None:
    _completed_run(db_session, when=NOW - timedelta(days=1), findings=[("gdacs", "severity_shape")])

    with (
        _patch_audit([_finding("gdacs", "severity_shape")]),
        patch("app.audit.task._pushover_send") as push,
    ):
        result = run_audit(db_session, now=NOW)

    assert result["new"] == 0
    assert result["pushed"] == 0
    assert _notifications(db_session) == []
    push.assert_not_called()
    assert len(db_session.execute(select(AuditRunRow)).scalars().all()) == 2


def test_new_finding_is_pushed(db_session: Session) -> None:
    _completed_run(db_session, when=NOW - timedelta(days=1), findings=[("gdacs", "severity_shape")])
    current = [_finding("gdacs", "severity_shape"), _finding("nasa-firms", "severity_constant")]

    with _patch_audit(current), patch("app.audit.task._pushover_send"):
        run_audit(db_session, now=NOW)

    assert _notifications(db_session) == ["1 new audit findings: nasa-firms severity_constant"]


def test_resolved_finding_is_recorded_not_pushed(db_session: Session) -> None:
    _completed_run(
        db_session,
        when=NOW - timedelta(days=1),
        findings=[("gdacs", "severity_shape"), ("nasa-firms", "severity_constant")],
    )

    with (
        _patch_audit([_finding("gdacs", "severity_shape")]),
        patch("app.audit.task._pushover_send"),
    ):
        run_audit(db_session, now=NOW)

    assert _notifications(db_session) == []
    latest = (
        db_session.execute(select(AuditRunRow).order_by(AuditRunRow.started_at.desc()))
        .scalars()
        .first()
    )
    rows = (
        db_session.execute(select(AuditFindingRow).where(AuditFindingRow.run_id == latest.id))
        .scalars()
        .all()
    )
    assert [r.source for r in rows] == ["gdacs"]


def test_crashed_run_is_skipped_as_the_baseline(db_session: Session) -> None:
    """The one case that decides whether this channel survives.

    A crashed run never reached most sources. Diffing against it would make
    every finding it missed look new and page ~50 false positives the next
    morning.
    """
    _completed_run(
        db_session,
        when=NOW - timedelta(days=2),
        findings=[("gdacs", "severity_shape"), ("nasa-firms", "severity_constant")],
    )
    _completed_run(
        db_session,
        when=NOW - timedelta(days=1),
        findings=[("gdacs", "severity_shape")],
        finished=False,
    )
    current = [_finding("gdacs", "severity_shape"), _finding("nasa-firms", "severity_constant")]

    with _patch_audit(current), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    assert result["new"] == 0
    push.assert_not_called()


def test_findings_total_matches_the_rows_written(db_session: Session) -> None:
    findings = [_finding(f"source-{i}", "severity_constant") for i in range(7)]

    with _patch_audit(findings), patch("app.audit.task._pushover_send"):
        run_audit(db_session, now=NOW)

    run = db_session.execute(select(AuditRunRow)).scalars().one()
    rows = db_session.execute(select(AuditFindingRow)).scalars().all()
    assert run.findings_total == len(rows) == 7
    assert run.finished_at is not None


def test_clean_run_still_writes_a_row(db_session: Session) -> None:
    """ "Nothing wrong" and "never ran" must not look the same (#663)."""
    with _patch_audit([]), patch("app.audit.task._pushover_send") as push:
        result = run_audit(db_session, now=NOW)

    run = db_session.execute(select(AuditRunRow)).scalars().one()
    assert run.findings_total == 0
    assert run.finished_at is not None
    assert result["findings"] == 0
    push.assert_not_called()
