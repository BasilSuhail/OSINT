from app.jobs import heartbeat


def test_job_run_evicts_brain_on_start(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", lambda: calls.append("evict"))
    with heartbeat.job_run("cluster", session_factory=_fake_factory()):
        pass
    assert calls == ["evict"]


def test_job_run_skips_eviction_when_flag_false(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", lambda: calls.append("evict"))
    with heartbeat.job_run("brain-narrate", session_factory=_fake_factory(), evict_brain=False):
        pass
    assert calls == []


def test_job_run_swallows_evict_failure(monkeypatch):
    def boom():
        raise RuntimeError("ollama down")

    monkeypatch.setattr(heartbeat.settings, "brain_enabled", True)
    monkeypatch.setattr("app.brain.client.evict", boom)
    # must not raise — eviction is best-effort
    with heartbeat.job_run("cluster", session_factory=_fake_factory()):
        pass


def _fake_factory():
    """Minimal in-memory session factory for the heartbeat rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db_models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
