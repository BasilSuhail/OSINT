"""GET /audit/latest — the source-data audit, where a person can see it (#692).

#669 gave the audit a clock and a history and nothing read it. Two of its nine
findings started the work that became #681, #682, #684, #689, #690 and #691, and
they were found by running a script by hand and reading a terminal. A guardrail
nobody can see only works when somebody remembers to look.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import AuditFindingRow, AuditRunRow, Base

NOW = datetime(2026, 7, 30, 3, 40, tzinfo=UTC)


def _run(
    session: Session,
    *,
    when: datetime,
    findings: list[tuple[str, str]],
    finished: bool = True,
    sources: int = 53,
) -> AuditRunRow:
    run = AuditRunRow(
        started_at=when,
        finished_at=when if finished else None,
        sources_measured=sources,
        findings_total=len(findings),
    )
    session.add(run)
    session.flush()
    for source, check in findings:
        session.add(
            AuditFindingRow(
                run_id=run.id,
                source=source,
                check_name=check,
                detail=f"{source} tripped {check}",
            )
        )
    return run


def _client(seed) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        seed(s)
        s.commit()

    def override():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_latest_run_reports_its_findings() -> None:
    def seed(s: Session) -> None:
        _run(
            s,
            when=NOW,
            findings=[
                ("fred", "composite_reachability"),
                ("opensky-adsb", "severity_constant"),
            ],
        )

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["present"] is True
        assert body["findings_total"] == 2
        assert body["sources_measured"] == 53
        assert {f["source"] for f in body["findings"]} == {"fred", "opensky-adsb"}
        assert body["findings"][0]["check"]
        assert body["findings"][0]["detail"]
    finally:
        app.dependency_overrides.clear()


def test_the_delta_against_the_previous_run_is_reported() -> None:
    # The number on its own says little; whether it moved is the whole point of
    # having a history rather than a snapshot.
    def seed(s: Session) -> None:
        _run(s, when=NOW - timedelta(days=1), findings=[("fred", "composite_reachability")])
        _run(
            s,
            when=NOW,
            findings=[
                ("fred", "composite_reachability"),
                ("gdelt", "country_coverage"),
                ("rss-cnn-world", "severity_shape"),
            ],
        )

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["findings_total"] == 3
        assert body["previous_findings_total"] == 1
        assert body["delta"] == 2
    finally:
        app.dependency_overrides.clear()


def test_a_crashed_run_is_not_treated_as_the_previous_one() -> None:
    # Same rule the notifier uses: a run that never finished never reached most
    # sources, so diffing against it would invent movement that did not happen.
    def seed(s: Session) -> None:
        _run(s, when=NOW - timedelta(days=2), findings=[("fred", "composite_reachability")])
        _run(s, when=NOW - timedelta(days=1), findings=[], finished=False)
        _run(
            s,
            when=NOW,
            findings=[("fred", "composite_reachability"), ("gdelt", "country_coverage")],
        )

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["previous_findings_total"] == 1
        assert body["delta"] == 1
    finally:
        app.dependency_overrides.clear()


def test_a_first_run_has_no_delta_rather_than_a_zero_one() -> None:
    # Nothing to compare against is not the same claim as "nothing changed".
    def seed(s: Session) -> None:
        _run(s, when=NOW, findings=[("fred", "composite_reachability")])

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["previous_findings_total"] is None
        assert body["delta"] is None
    finally:
        app.dependency_overrides.clear()


def test_a_clean_run_is_reported_as_present_with_no_findings() -> None:
    # "Clean" and "never ran" must not look the same — the #663 failure shape.
    def seed(s: Session) -> None:
        _run(s, when=NOW, findings=[])

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["present"] is True
        assert body["findings_total"] == 0
        assert body["findings"] == []
    finally:
        app.dependency_overrides.clear()


def test_never_having_run_says_so_instead_of_implying_a_clean_bill() -> None:
    def seed(s: Session) -> None:
        return None

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert body["present"] is False
        assert body["findings"] == []
        assert body["findings_total"] is None
    finally:
        app.dependency_overrides.clear()


def test_an_unfinished_run_is_not_reported_as_the_latest() -> None:
    def seed(s: Session) -> None:
        _run(s, when=NOW - timedelta(days=1), findings=[("fred", "composite_reachability")])
        _run(s, when=NOW, findings=[("gdelt", "country_coverage")], finished=False)

    client = _client(seed)
    try:
        body = client.get("/audit/latest").json()

        assert {f["source"] for f in body["findings"]} == {"fred"}
    finally:
        app.dependency_overrides.clear()
