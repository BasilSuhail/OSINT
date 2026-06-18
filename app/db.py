"""SQLAlchemy engine + session factory.

A single engine is created lazily so importing this module does not require
a reachable database — tests can override the URL before any session is
actually opened.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the singleton engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.postgres_url,
            future=True,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager that yields a session and commits on success / rolls back on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_testing(url: str) -> Engine:
    """Test-only helper to point the engine at an alternate database URL.

    The pytest fixture in tests/conftest.py calls this before any persistence
    code runs so the production URL is never touched by tests.
    """
    global _engine, _session_factory
    _engine = create_engine(url, future=True, pool_pre_ping=True)
    _session_factory = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return _engine
