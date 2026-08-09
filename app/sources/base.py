"""Fetcher contract.

Every source-specific fetcher subclasses `Fetcher`. The Celery task is the only
place that touches the database; fetchers are pure functions over HTTP.

See `docs/architecture/03-ingestion.md` for the design rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from app.models import Event

Queue = Literal["fast", "slow"]


class SourceMisconfiguredError(RuntimeError):
    """A scheduled source cannot run until its local configuration changes.

    This is neither a transport failure worth retrying nor a healthy empty
    response.  The universal task wrapper records it as its own output state.
    """


@dataclass(frozen=True)
class FetchBatch:
    """Fetcher output plus a fact only the fetcher itself can know.

    Most fetchers return a plain list.  Static inputs may return this wrapper
    when they checked the same immutable revision and deliberately skipped
    reparsing it; an empty list alone cannot distinguish that from a source
    which answered with no usable records.
    """

    events: list[Event] = field(default_factory=list)
    unchanged: bool = False


class Fetcher(ABC):
    """Pure HTTP-side fetcher. No database, no Redis, no Celery awareness."""

    #: Source slug, used as `events.source` and as the Celery task name.
    name: str

    #: Celery queue this fetcher runs in. See `docs/architecture/03-ingestion.md`.
    queue: Queue

    #: Does a URL from this fetcher name the same resource every time?
    #:
    #: True for every feed and API endpoint here: `arabnews.com/rss.xml` is the
    #: same document today and tomorrow, so a 404 from it is permanent and the
    #: quarantine should stop asking (#567).
    #:
    #: False for a source addressed by time, where each fetch names a different
    #: object — GDELT's export file carries the fifteen-minute window in its
    #: name. There a 404 means "not published yet", and quarantining on it
    #: parks a working feed (#808).
    stable_urls: bool = True

    @abstractmethod
    def fetch(self) -> list[Event] | FetchBatch:
        """Pull the source and return a list of canonical `Event` objects."""

    @abstractmethod
    def archive_path(self) -> str:
        """Parquet partition path under `/mnt/data/parquet/` for this fetcher."""
