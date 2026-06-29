"""abuse.ch cyber-threat feeds — URLhaus + Feodo Tracker.

Both endpoints are free, no-key, community-run. CSVs refreshed every
~5 min. We poll every 15 min to be polite.

- URLhaus: recently observed malware-distribution URLs.
- Feodo Tracker: active botnet C2 IPs (Emotet, TrickBot, Dridex,
  QakBot family).

Each row → one Event with category = CYBER, severity = 0.55 by
default. Bumped to 0.75 when the row's tag set carries one of the
heavy keywords (ransomware / botnet / phishing-kit / c2). See
issue #162.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlparse

import httpx

from app.enrichment.ip_geo import IpGeo, lookup_ip, public_ip_or_none
from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

URLHAUS_URL: Final[str] = "https://urlhaus.abuse.ch/downloads/csv_recent/"
FEODO_URL: Final[str] = "https://feodotracker.abuse.ch/downloads/ipblocklist.csv"
ABUSE_CH_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

CYBER_DEFAULT_SEVERITY: Final[float] = 0.55
CYBER_HEAVY_SEVERITY: Final[float] = 0.75
_HEAVY_TAGS: Final[tuple[str, ...]] = (
    "ransomware",
    "botnet",
    "phishing",
    "phishing-kit",
    "c2",
    "trojan",
    "stealer",
)


def _strip_csv_comments(text: str) -> str:
    """abuse.ch CSVs prefix every comment line with '#'. Strip those."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


def _hash_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _severity_for_tags(tags: str) -> float:
    low = tags.lower()
    for kw in _HEAVY_TAGS:
        if kw in low:
            return CYBER_HEAVY_SEVERITY
    return CYBER_DEFAULT_SEVERITY


def _geo_payload(geo: IpGeo | None) -> dict[str, object]:
    if geo is None:
        return {}
    return {
        "geo_city": geo.city,
        "geo_country": geo.country,
        "geo_lat": geo.lat,
        "geo_lon": geo.lon,
    }


def _geo_for_host(url: str, geo_by_ip: dict[str, IpGeo] | None) -> IpGeo | None:
    if not geo_by_ip:
        return None
    host = urlparse(url).hostname
    ip = public_ip_or_none(host)
    return geo_by_ip.get(ip) if ip else None


def parse_urlhaus_csv(
    body: str,
    *,
    fetched_at: datetime,
    geo_by_ip: dict[str, IpGeo] | None = None,
) -> list[Event]:
    """URLhaus CSV columns: id, dateadded, url, url_status, last_online,
    threat, tags, urlhaus_link, reporter."""
    cleaned = _strip_csv_comments(body)
    out: list[Event] = []
    reader = csv.reader(io.StringIO(cleaned))
    for row in reader:
        if len(row) < 9:
            continue
        try:
            id_, date_added, url, status, _last_online, threat, tags, link, reporter = row[:9]
        except ValueError:
            continue
        url = url.strip()
        if not url:
            continue
        geo = _geo_for_host(url, geo_by_ip)
        try:
            occurred_at = datetime.strptime(date_added.strip(), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            occurred_at = fetched_at

        out.append(
            Event(
                source="abuse-ch-urlhaus",
                source_event_id=id_.strip() or _hash_id("urlhaus", url),
                occurred_at=occurred_at,
                fetched_at=fetched_at,
                category=Category.CYBER,
                severity=_severity_for_tags(tags),
                confidence=None,
                keywords=["cyber", "urlhaus", "malware-url"],
                country=geo.country if geo else None,
                lat=geo.lat if geo else None,
                lon=geo.lon if geo else None,
                payload={
                    "url": url,
                    "status": status.strip() or None,
                    "threat": threat.strip() or None,
                    "tags": [t for t in tags.split(",") if t.strip()],
                    "reporter": reporter.strip() or None,
                    "urlhaus_link": link.strip() or None,
                    **_geo_payload(geo),
                },
            )
        )
    return out


def parse_feodo_csv(
    body: str,
    *,
    fetched_at: datetime,
    geo_by_ip: dict[str, IpGeo] | None = None,
) -> list[Event]:
    """Feodo Tracker CSV columns: first_seen_utc, dst_ip, dst_port,
    c2_status, last_online, malware."""
    cleaned = _strip_csv_comments(body)
    out: list[Event] = []
    reader = csv.reader(io.StringIO(cleaned))
    for row in reader:
        if len(row) < 6:
            continue
        try:
            first_seen, dst_ip, dst_port, c2_status, _last_online, malware = row[:6]
        except ValueError:
            continue
        dst_ip = dst_ip.strip()
        if not dst_ip:
            continue
        geo = geo_by_ip.get(dst_ip) if geo_by_ip else None
        try:
            occurred_at = datetime.strptime(first_seen.strip(), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            occurred_at = fetched_at

        # Feodo is always botnet C2 — heavy band by default.
        out.append(
            Event(
                source="abuse-ch-feodo",
                source_event_id=_hash_id("feodo", dst_ip, dst_port.strip()),
                occurred_at=occurred_at,
                fetched_at=fetched_at,
                category=Category.CYBER,
                severity=CYBER_HEAVY_SEVERITY,
                confidence=None,
                keywords=["cyber", "feodo", "botnet", "c2", malware.strip().lower() or "unknown"],
                country=geo.country if geo else None,
                lat=geo.lat if geo else None,
                lon=geo.lon if geo else None,
                payload={
                    "dst_ip": dst_ip,
                    "dst_port": int(dst_port.strip()) if dst_port.strip().isdigit() else None,
                    "c2_status": c2_status.strip() or None,
                    "malware": malware.strip() or None,
                    **_geo_payload(geo),
                },
            )
        )
    return out


class _AbuseChFetcher(Fetcher):
    """Shared HTTP client behaviour for both abuse.ch fetchers."""

    queue = "slow"
    url: str

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def _fetch_body(self) -> str:
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": ABUSE_CH_USER_AGENT},
        ) as client:
            response = client.get(self.url)
            response.raise_for_status()
            return response.text

    def _geo_by_ip(self, ips: list[str]) -> dict[str, IpGeo]:
        if not settings.cyber_geo_enabled or settings.cyber_geo_max_lookups <= 0:
            return {}
        out: dict[str, IpGeo] = {}
        seen: set[str] = set()
        with httpx.Client(timeout=10.0) as client:
            for raw in ips:
                ip = public_ip_or_none(raw)
                if ip is None or ip in seen:
                    continue
                seen.add(ip)
                if len(out) >= settings.cyber_geo_max_lookups:
                    break
                geo = lookup_ip(ip, client=client)
                if geo is not None:
                    out[ip] = geo
        return out


class UrlhausFetcher(_AbuseChFetcher):
    name = "abuse-ch-urlhaus"
    url = URLHAUS_URL

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        body = self._fetch_body()
        ips: list[str] = []
        for line in _strip_csv_comments(body).splitlines():
            parts = line.split(",")
            if len(parts) >= 3:
                host = urlparse(parts[2].strip()).hostname
                if host:
                    ips.append(host)
        return parse_urlhaus_csv(body, fetched_at=fetched_at, geo_by_ip=self._geo_by_ip(ips))

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/abuse-ch-urlhaus/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )


class FeodoFetcher(_AbuseChFetcher):
    name = "abuse-ch-feodo"
    url = FEODO_URL

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        body = self._fetch_body()
        ips = [
            row.split(",")[1].strip()
            for row in _strip_csv_comments(body).splitlines()
            if "," in row
        ]
        return parse_feodo_csv(body, fetched_at=fetched_at, geo_by_ip=self._geo_by_ip(ips))

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/abuse-ch-feodo/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )
