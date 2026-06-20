"""Tests for `app.enrichment.country.country_for`.

Spot-check 12 well-known points on land and 2 in international water / polar.
The 110 m Natural Earth dataset is coarse near borders; pick interior points.
"""

from __future__ import annotations

import pytest

from app.enrichment.country import country_for


@pytest.mark.parametrize(
    "lat,lon,iso",
    [
        (52.52, 13.40, "DE"),  # Berlin
        (-12.04, -77.04, "PE"),  # Lima
        (35.68, 139.69, "JP"),  # Tokyo
        (40.71, -74.01, "US"),  # New York
        (-33.87, 151.21, "AU"),  # Sydney
        (30.04, 31.24, "EG"),  # Cairo
        (64.13, -21.94, "IS"),  # Reykjavik
        (19.08, 72.88, "IN"),  # Mumbai
        (6.52, 3.38, "NG"),  # Lagos
        (-23.55, -46.63, "BR"),  # São Paulo
        (55.75, 37.62, "RU"),  # Moscow
        (-85.0, 0.0, "AQ"),  # Antarctica interior
    ],
)
def test_known_land_points(lat: float, lon: float, iso: str) -> None:
    assert country_for(lat, lon) == iso


@pytest.mark.parametrize(
    "lat,lon",
    [
        (0.0, -30.0),  # mid-Atlantic
        (0.0, -160.0),  # mid-Pacific
    ],
)
def test_open_ocean_returns_none(lat: float, lon: float) -> None:
    assert country_for(lat, lon) is None


def test_out_of_range_returns_none() -> None:
    assert country_for(95.0, 0.0) is None
    assert country_for(0.0, 200.0) is None
    assert country_for(-95.0, 0.0) is None


def test_none_inputs_return_none() -> None:
    assert country_for(None, None) is None  # type: ignore[arg-type]
    assert country_for(0.0, None) is None  # type: ignore[arg-type]


def test_repeated_query_is_cheap() -> None:
    # Just verify caching path doesn't blow up under repeated calls.
    for _ in range(100):
        assert country_for(52.52, 13.40) == "DE"
