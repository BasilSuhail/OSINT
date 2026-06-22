"""Name → fetcher instance registry.

The Celery task `app.tasks.run_fetcher(name)` looks up the fetcher here so the
task body stays generic and tests can register stubs without touching the
shipping fetchers.
"""

from __future__ import annotations

from app.sources.abuse_ch_fetchers import FeodoFetcher, UrlhausFetcher
from app.sources.base import Fetcher
from app.sources.eonet_fetcher import EonetFetcher
from app.sources.fred_fetcher import FredFetcher
from app.sources.gdacs_fetcher import GdacsFetcher
from app.sources.gdelt_fetcher import GdeltFetcher
from app.sources.nasa_firms_fetcher import NasaFirmsFetcher
from app.sources.opensky_fetcher import OpenSkyFetcher
from app.sources.polymarket_fetcher import PolymarketFetcher
from app.sources.rss_registry import build_rss_fetchers
from app.sources.uk_police_fetcher import UKPoliceFetcher
from app.sources.usgs_quake_fetcher import UsgsQuakeFetcher
from app.sources.yfinance_fetcher import YFinanceFetcher

_REGISTRY: dict[str, Fetcher] = {
    "yfinance": YFinanceFetcher(),
    "fred": FredFetcher(),
    "gdelt": GdeltFetcher(),
    "usgs-quake": UsgsQuakeFetcher(),
    "gdacs": GdacsFetcher(),
    "nasa-firms": NasaFirmsFetcher(),
    "eonet": EonetFetcher(),
    "uk-police": UKPoliceFetcher(),
    "opensky-adsb": OpenSkyFetcher(),
    "abuse-ch-urlhaus": UrlhausFetcher(),
    "abuse-ch-feodo": FeodoFetcher(),
    "polymarket": PolymarketFetcher(),
    # 25+ RSS feeds loaded from app/sources/rss_feeds.json. Each becomes
    # a dynamically named RssNewsFetcher subclass with the slug as its
    # name. See app/sources/rss_registry.py + issue #158.
    **build_rss_fetchers(),
}


def get_fetcher(name: str) -> Fetcher:
    """Return the registered fetcher for `name`. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown fetcher: {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def register(name: str, fetcher: Fetcher) -> None:
    """Register or replace a fetcher under `name`. Used by tests."""
    _REGISTRY[name] = fetcher


def deregister(name: str) -> None:
    """Remove a fetcher from the registry. Used by tests for cleanup."""
    _REGISTRY.pop(name, None)
