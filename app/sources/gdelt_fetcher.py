"""Module B — Geopolitical events via GDELT v2 15-minute exports.

The HTTP layer is intentionally thin. Two side-effecting steps —
`_latest_export_url` (the lastupdate.txt redirect) and `_download_export`
(the zipped CSV) — are wrapped around pure helpers that can be unit tested
without network access:

- `parse_lastupdate(text)` extracts the export URL
- `read_zip_csv(bytes)` unzips and decodes the CSV body
- `parse_csv_body(text)` (in `gdelt_parser.py`) converts rows into Events
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Final

import httpx

from app.models import Event
from app.sources.base import Fetcher
from app.sources.gdelt_parser import parse_csv_body

GDELT_LASTUPDATE_URL: Final[str] = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"


def parse_lastupdate(text: str) -> str | None:
    """Extract the export-CSV zip URL from a GDELT lastupdate.txt body.

    The file lists three URLs per update (export, mentions, gkg); this returns
    the export one. Returns None if no matching line is present.
    """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1].endswith(".export.CSV.zip"):
            return parts[-1]
    return None


def read_zip_csv(zip_bytes: bytes) -> str:
    """Unzip a GDELT export zip and return the first member's CSV text."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        if not names:
            return ""
        with archive.open(names[0]) as fp:
            return fp.read().decode("utf-8", errors="replace")


class GdeltFetcher(Fetcher):
    """Pulls the most recent GDELT v2 export and emits canonical events."""

    name = "gdelt"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(timezone.utc)
        export_url = self._latest_export_url()
        if export_url is None:
            return []
        csv_body = self._download_export(export_url)
        return parse_csv_body(csv_body, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(timezone.utc)
        return (
            f"/mnt/data/parquet/gdelt/year={now.year}"
            f"/month={now.month:02d}/day={now.day:02d}/"
        )

    def _latest_export_url(self) -> str | None:
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": GDELT_USER_AGENT}
        ) as client:
            response = client.get(GDELT_LASTUPDATE_URL)
            response.raise_for_status()
            return parse_lastupdate(response.text)

    def _download_export(self, url: str) -> str:
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": GDELT_USER_AGENT}
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return read_zip_csv(response.content)
