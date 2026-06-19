"""Name → fetcher instance registry.

The Celery task `app.tasks.run_fetcher(name)` looks up the fetcher here so the
task body stays generic and tests can register stubs without touching the
shipping fetchers.
"""

from __future__ import annotations

from app.sources.base import Fetcher
from app.sources.fred_fetcher import FredFetcher
from app.sources.gdelt_fetcher import GdeltFetcher
from app.sources.yfinance_fetcher import YFinanceFetcher

_REGISTRY: dict[str, Fetcher] = {
    "yfinance": YFinanceFetcher(),
    "fred": FredFetcher(),
    "gdelt": GdeltFetcher(),
}


def get_fetcher(name: str) -> Fetcher:
    """Return the registered fetcher for `name`. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown fetcher: {name!r}. Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def register(name: str, fetcher: Fetcher) -> None:
    """Register or replace a fetcher under `name`. Used by tests."""
    _REGISTRY[name] = fetcher


def deregister(name: str) -> None:
    """Remove a fetcher from the registry. Used by tests for cleanup."""
    _REGISTRY.pop(name, None)
