from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.db_models import Base, BrainNarrativeRow


def _client_with_db():
    # StaticPool + check_same_thread=False: FastAPI's TestClient runs sync
    # endpoints in a worker thread, and SQLAlchemy's default SingletonThreadPool
    # hands each thread its own private in-memory SQLite DB (so the table
    # created here would look missing from the endpoint's thread).
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app), factory


def test_latest_empty_when_none():
    client, _ = _client_with_db()
    body = client.get("/brain/narrative/latest").json()
    assert body["present"] is False
    assert body["payload"] is None
    app.dependency_overrides.clear()


def test_latest_returns_newest():
    client, factory = _client_with_db()
    with factory() as session:
        session.add(
            BrainNarrativeRow(
                created_at=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
                model="qwen2.5:1.5b-instruct-q4_K_M",
                payload={"headline": "quiet"},
                input_digest="sha256:a",
            )
        )
        session.commit()
    body = client.get("/brain/narrative/latest").json()
    assert body["present"] is True
    assert body["payload"]["headline"] == "quiet"
    app.dependency_overrides.clear()
