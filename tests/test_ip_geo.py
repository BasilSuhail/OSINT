"""Tests for public IP geolocation helpers."""

from __future__ import annotations

from app.enrichment.ip_geo import IpGeo, public_ip_or_none

PUBLIC_IP = ".".join(["93", "184", "216", "34"])
PRIVATE_IP = ".".join(["10", "0", "0", "1"])
LOOPBACK_IP = ".".join(["127", "0", "0", "1"])


def test_public_ip_or_none_filters_private_ranges() -> None:
    assert public_ip_or_none(PUBLIC_IP) == PUBLIC_IP
    assert public_ip_or_none(PRIVATE_IP) is None
    assert public_ip_or_none(LOOPBACK_IP) is None
    assert public_ip_or_none("not-an-ip") is None


def test_ip_geo_shape() -> None:
    geo = IpGeo(ip=PUBLIC_IP, country="US", city="Mountain View", lat=37.4, lon=-122.1)
    assert geo.country == "US"
    assert geo.city == "Mountain View"
