"""Shared pytest fixtures.

Tests run against an in-memory SQLite database with the schema created from
the SQLAlchemy models. This keeps the unit suite hermetic — no docker required.
Postgres-specific behaviour (JSONB GIN indexes, ARRAY introspection) is
exercised by the migration in CI against a real Postgres container.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_models import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Yield a session against a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
