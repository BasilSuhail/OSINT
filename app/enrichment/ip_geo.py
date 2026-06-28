"""Best-effort public IP geolocation for cyber indicators."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, Final

import httpx

IP_API_TEMPLATE: Final[str] = (
    "http://ip-api.com/json/{ip}?fields=status,countryCode,city,lat,lon,query"
)
IP_GEO_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"


@dataclass(frozen=True)
class IpGeo:
    ip: str
    country: str | None
    city: str | None
    lat: float | None
    lon: float | None


def public_ip_or_none(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = ip_address(raw.strip())
    except ValueError:
        return None
    if parsed.is_private or parsed.is_loopback or parsed.is_reserved or parsed.is_multicast:
        return None
    return str(parsed)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def lookup_ip(
    ip: str,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 10.0,
) -> IpGeo | None:
    ip_clean = public_ip_or_none(ip)
    if ip_clean is None:
        return None
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout_seconds, headers={"User-Agent": IP_GEO_USER_AGENT})
    try:
        response = client.get(IP_API_TEMPLATE.format(ip=ip_clean))
        response.raise_for_status()
        body = response.json()
    finally:
        if owns_client:
            client.close()
    if body.get("status") != "success":
        return None
    country = body.get("countryCode")
    if not isinstance(country, str) or len(country) != 2:
        country = None
    city = body.get("city")
    return IpGeo(
        ip=ip_clean,
        country=country.upper() if country else None,
        city=city.strip() if isinstance(city, str) and city.strip() else None,
        lat=_float_or_none(body.get("lat")),
        lon=_float_or_none(body.get("lon")),
    )
