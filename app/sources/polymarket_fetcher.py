"""Polymarket public prediction-market fetcher.

Gamma API at https://gamma-api.polymarket.com/markets is free + no key
+ paginated. Each market doc has an array of outcomes with current
prices and volume. We read the active markets only.

Each market → one Event with category = MARKET. Severity proxies the
"tail-event awareness" signal: the implied probability of the YES /
first outcome maps onto a 0..1 band. The intuition: a market trading
at 0.5 carries the most stress (genuinely uncertain), while 0.05 or
0.95 carry less because participants have made up their minds.

severity = 1 - abs(p - 0.5) * 2  ∈  [0, 1]
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

POLYMARKET_URL: Final[str] = "https://gamma-api.polymarket.com/markets"
POLYMARKET_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"


def _safe_first_price(prices_raw: Any) -> float | None:
    """The Polymarket API returns ``outcomePrices`` as a JSON-encoded
    string of a list; e.g. '"[\\"0.65\\", \\"0.35\\"]"'. Coerce to the
    first float or return None."""
    if isinstance(prices_raw, list):
        items = prices_raw
    elif isinstance(prices_raw, str):
        import json

        try:
            items = json.loads(prices_raw)
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(items, list) or not items:
        return None
    try:
        return float(items[0])
    except (TypeError, ValueError):
        return None


def _severity_for_price(p: float | None) -> float:
    """Highest stress at 0.5; declines linearly to 0 at the tails."""
    if p is None:
        return 0.3
    return max(0.0, min(1.0, 1.0 - abs(p - 0.5) * 2.0))


def _market_to_event(market: dict[str, Any], fetched_at: datetime) -> Event | None:
    """Normalise one Polymarket market doc to an Event."""
    market_id = market.get("id") or market.get("conditionId")
    if not market_id:
        return None
    question = (market.get("question") or "").strip()
    slug = market.get("slug") or None

    yes_price = _safe_first_price(market.get("outcomePrices"))
    volume = market.get("volume")
    liquidity = market.get("liquidity")

    payload = {
        "question": question or None,
        "slug": slug,
        "yes_price": yes_price,
        "volume": volume,
        "liquidity": liquidity,
        "end_date": market.get("endDate"),
        "category": market.get("category"),
    }

    return Event(
        source="polymarket",
        source_event_id=str(market_id),
        occurred_at=fetched_at,
        fetched_at=fetched_at,
        category=Category.MARKET,
        severity=_severity_for_price(yes_price),
        confidence=None,
        keywords=["polymarket", "prediction-market"],
        country=None,
        lat=None,
        lon=None,
        payload=payload,
    )


def parse_polymarket_body(body: Any, *, fetched_at: datetime) -> list[Event]:
    """Pure transformation: Polymarket JSON list → Events."""
    if not isinstance(body, list):
        return []
    out: list[Event] = []
    for market in body:
        if not isinstance(market, dict):
            continue
        ev = _market_to_event(market, fetched_at)
        if ev is not None:
            out.append(ev)
    return out


class PolymarketFetcher(Fetcher):
    name = "polymarket"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 30.0, limit: int = 100) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.limit = limit

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": POLYMARKET_USER_AGENT, "Accept": "application/json"},
        ) as client:
            response = client.get(
                POLYMARKET_URL, params={"active": "true", "limit": str(self.limit)}
            )
            response.raise_for_status()
            return parse_polymarket_body(response.json(), fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/polymarket/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        )
