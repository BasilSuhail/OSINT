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

import httpx

from app.models import Category, Event
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


def parse_urlhaus_csv(body: str, *, fetched_at: datetime) -> list[Event]:
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
                country=None,
                lat=None,
                lon=None,
                payload={
                    "url": url,
                    "status": status.strip() or None,
                    "threat": threat.strip() or None,
                    "tags": [t for t in tags.split(",") if t.strip()],
                    "reporter": reporter.strip() or None,
                    "urlhaus_link": link.strip() or None,
                },
            )
        )
    return out


def parse_feodo_csv(body: str, *, fetched_at: datetime) -> list[Event]:
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
                country=None,
                lat=None,
                lon=None,
                payload={
                    "dst_ip": dst_ip,
                    "dst_port": int(dst_port.strip()) if dst_port.strip().isdigit() else None,
                    "c2_status": c2_status.strip() or None,
                    "malware": malware.strip() or None,
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


class UrlhausFetcher(_AbuseChFetcher):
    name = "abuse-ch-urlhaus"
    url = URLHAUS_URL

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        return parse_urlhaus_csv(self._fetch_body(), fetched_at=fetched_at)

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
        return parse_feodo_csv(self._fetch_body(), fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/abuse-ch-feodo/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )
