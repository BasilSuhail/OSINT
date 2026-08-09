"""Name → fetcher instance registry.

The Celery task `app.tasks.run_fetcher(name)` looks up the fetcher here so the
task body stays generic and tests can register stubs without touching the
shipping fetchers.
"""

from __future__ import annotations

from app.sources.base import Fetcher

CORE_FETCHER_NAMES: frozenset[str] = frozenset(
    {
        "yfinance",
        "fred",
        "gdelt",
        "acled",
        "emdat",
        "usgs-quake",
        "gdacs",
        "nasa-firms",
        "eonet",
        "uk-police",
        "opensky-adsb",
        "abuse-ch-urlhaus",
        "abuse-ch-feodo",
        "polymarket",
    }
)

_REGISTRY: dict[str, Fetcher] | None = None
_OVERRIDES: dict[str, Fetcher] = {}


def _build_registry() -> dict[str, Fetcher]:
    # Import fetchers only when a fetch task actually runs. Several fetchers
    # pull pandas/feedparser/geospatial helpers at import time; eager loading
    # them in every idle Celery worker/beat process wastes resident memory.
    from app.sources.abuse_ch_fetchers import FeodoFetcher, UrlhausFetcher
    from app.sources.acled_fetcher import AcledFetcher
    from app.sources.emdat_fetcher import EmdatFetcher
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

    return {
        "yfinance": YFinanceFetcher(),
        "fred": FredFetcher(),
        "gdelt": GdeltFetcher(),
        "acled": AcledFetcher(),
        "emdat": EmdatFetcher(),
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


def _registry() -> dict[str, Fetcher]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
        _REGISTRY.update(_OVERRIDES)
    return _REGISTRY


def get_fetcher(name: str) -> Fetcher:
    """Return the registered fetcher for `name`. Raises KeyError if unknown."""
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    registry = _registry()
    if name not in registry:
        raise KeyError(f"unknown fetcher: {name!r}. Registered: {sorted(registry)}")
    return registry[name]


def registered_names() -> frozenset[str]:
    """Active fetcher slugs without importing or constructing fetchers.

    Audit runs need the registry's universe even when a source has never made
    an event row. RSS membership remains data-driven and runtime test
    registrations remain visible.
    """
    from app.sources.rss_registry import feed_enabled_map

    rss = {source for source, enabled in feed_enabled_map().items() if enabled}
    return frozenset(CORE_FETCHER_NAMES | rss | set(_OVERRIDES))


def register(name: str, fetcher: Fetcher) -> None:
    """Register or replace a fetcher under `name`. Used by tests."""
    _OVERRIDES[name] = fetcher
    if _REGISTRY is not None:
        _REGISTRY[name] = fetcher


def deregister(name: str) -> None:
    """Remove a fetcher from the registry. Used by tests for cleanup."""
    _OVERRIDES.pop(name, None)
    if _REGISTRY is not None:
        _REGISTRY.pop(name, None)
