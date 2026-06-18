"""Fetcher contract.

Every source-specific fetcher subclasses `Fetcher`. The Celery task is the only
place that touches the database; fetchers are pure functions over HTTP.

See `docs/architecture/03-ingestion.md` for the design rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from app.models import Event

Queue = Literal["fast", "slow"]


class Fetcher(ABC):
    """Pure HTTP-side fetcher. No database, no Redis, no Celery awareness."""

    #: Source slug, used as `events.source` and as the Celery task name.
    name: str

    #: Celery queue this fetcher runs in. See `docs/architecture/03-ingestion.md`.
    queue: Queue

    @abstractmethod
    def fetch(self) -> list[Event]:
        """Pull the source and return a list of canonical `Event` objects."""

    @abstractmethod
    def archive_path(self) -> str:
        """Parquet partition path under `/mnt/data/parquet/` for this fetcher."""
