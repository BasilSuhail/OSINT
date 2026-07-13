from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.brain import task as brain_task
from app.db_models import Base, BrainNarrativeRow


def _factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_narrate_persists_row_when_allowed(monkeypatch):
    factory = _factory()
    monkeypatch.setattr(brain_task, "_session_factory", lambda: factory)
    monkeypatch.setattr(brain_task.gate, "should_run", lambda session, now=None: (True, "ok"))
    monkeypatch.setattr(
        brain_task.client,
        "generate_json",
        lambda prompt: {"headline": "quiet", "world": "w", "system": "s", "watch": []},
    )
    result = brain_task._narrate_body(now=datetime(2026, 7, 12, tzinfo=UTC))
    assert result["persisted"] is True
    with factory() as session:
        row = session.execute(select(BrainNarrativeRow)).scalar_one()
        assert row.payload["headline"] == "quiet"


def test_narrate_skips_when_gated(monkeypatch):
    factory = _factory()
    monkeypatch.setattr(brain_task, "_session_factory", lambda: factory)
    monkeypatch.setattr(brain_task.gate, "should_run", lambda session, now=None: (False, "low RAM"))
    result = brain_task._narrate_body(now=datetime(2026, 7, 12, tzinfo=UTC))
    assert result["persisted"] is False
    assert result["reason"] == "low RAM"
    with factory() as session:
        assert session.execute(select(BrainNarrativeRow)).first() is None


def test_narrate_body_real_gate_on_idle_box_persists(monkeypatch):
    """Regression for #409: the brain's own job_run row must not trip its
    own heavy-job gate. Drives the REAL gate.should_run inside a real
    job_run("brain-narrate") context — no mocking gate at all — on an
    otherwise idle box, and asserts the narrative is actually persisted."""
    factory = _factory()
    monkeypatch.setattr(brain_task, "_session_factory", lambda: factory)
    monkeypatch.setattr(brain_task.gate, "ram_free_mb", lambda: 8000)
    monkeypatch.setattr(
        brain_task.client,
        "generate_json",
        lambda prompt: {"headline": "quiet", "world": "w", "system": "s", "watch": []},
    )
    result = brain_task._narrate_body(now=datetime.now(UTC))
    assert result["persisted"] is True
    with factory() as session:
        rows = session.execute(select(BrainNarrativeRow)).scalars().all()
        assert len(rows) == 1
