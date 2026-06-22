"""Pure tests for ``app.sources.polymarket_fetcher``."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Category
from app.sources.polymarket_fetcher import (
    _market_to_event,
    _safe_first_price,
    _severity_for_price,
    parse_polymarket_body,
)

FETCHED_AT = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)


def _market(
    market_id: str = "m-1",
    question: str = "Will X happen by end of 2026?",
    prices: str = '["0.62", "0.38"]',
) -> dict:
    return {
        "id": market_id,
        "question": question,
        "slug": "will-x-happen",
        "outcomePrices": prices,
        "volume": 12345.6,
        "liquidity": 800.0,
        "endDate": "2026-12-31T00:00:00Z",
        "category": "Politics",
    }


def test_safe_first_price_handles_string_encoded_list() -> None:
    assert _safe_first_price('["0.65", "0.35"]') == 0.65


def test_safe_first_price_handles_native_list() -> None:
    assert _safe_first_price([0.42, 0.58]) == 0.42


def test_safe_first_price_returns_none_on_garbage() -> None:
    assert _safe_first_price(None) is None
    assert _safe_first_price("not json") is None
    assert _safe_first_price([]) is None


def test_severity_peaks_at_half() -> None:
    """Highest stress at p=0.5; declines toward the tails."""
    assert _severity_for_price(0.5) == 1.0
    assert _severity_for_price(0.0) == 0.0
    assert _severity_for_price(1.0) == 0.0


def test_severity_is_symmetric_around_half() -> None:
    a = _severity_for_price(0.3)
    b = _severity_for_price(0.7)
    assert abs(a - b) < 1e-9


def test_severity_none_falls_back_to_default() -> None:
    assert _severity_for_price(None) == 0.3


def test_market_to_event_happy_path() -> None:
    ev = _market_to_event(_market(), FETCHED_AT)
    assert ev is not None
    assert ev.source == "polymarket"
    assert ev.category == Category.MARKET
    assert ev.payload["yes_price"] == 0.62
    assert ev.payload["question"].startswith("Will X")


def test_market_to_event_returns_none_without_id() -> None:
    market = _market(market_id="")
    assert _market_to_event(market, FETCHED_AT) is None


def test_parse_body_filters_non_dicts() -> None:
    body = [_market("m-1"), "garbage", None, _market("m-2")]
    events = parse_polymarket_body(body, fetched_at=FETCHED_AT)
    assert len(events) == 2
    assert events[0].source_event_id == "m-1"
    assert events[1].source_event_id == "m-2"


def test_parse_body_non_list_returns_empty() -> None:
    assert parse_polymarket_body({"data": []}, fetched_at=FETCHED_AT) == []
    assert parse_polymarket_body(None, fetched_at=FETCHED_AT) == []
