"""Discover direct download links from known ACLED public pages.

This does not bypass myACLED access controls. It only reports CSV/XLSX/ZIP
links that are visible to the current HTTP session.
"""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

ACLED_SOURCE_URLS = [
    "https://acleddata.com/platform/explorer",
    "https://acleddata.com/platform/cast-conflict-alert-system",
    "https://acleddata.com/platform/conflict-exposure-calculator",
    "https://acleddata.com/aggregated/number-political-violence-events-country-year",
    "https://acleddata.com/aggregated/number-political-violence-events-country-month-year",
    "https://acleddata.com/aggregated/number-demonstration-events-country-year",
    "https://acleddata.com/aggregated/number-reported-fatalities-country-year",
    "https://acleddata.com/aggregated/number-reported-civilian-fatalities-direct-targeting-country-year",
    "https://acleddata.com/aggregated/number-events-targeting-civilians-country-year",
    "https://acleddata.com/aggregated/aggregated-data-africa",
    "https://acleddata.com/aggregated/aggregated-data-asia-pacific",
    "https://acleddata.com/aggregated/aggregated-data-europe-and-central-asia",
    "https://acleddata.com/aggregated/aggregated-data-latin-america-caribbean",
    "https://acleddata.com/aggregated/aggregated-data-middle-east",
    "https://acleddata.com/aggregated/aggregated-data-united-states-canada",
]

DOWNLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls", ".zip")


class LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name not in {"href", "src"} or not value:
                continue
            self.links.append(urljoin(self.base_url, value))


def _looks_like_download(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.casefold()
    if path.endswith(DOWNLOAD_EXTENSIONS):
        return True
    query = parsed.query.casefold()
    return any(token in query for token in ("format=csv", "download=csv", "export=csv"))


def extract_download_links(html: str, base_url: str) -> list[str]:
    parser = LinkParser(base_url)
    parser.feed(html)
    links = {link for link in parser.links if _looks_like_download(link)}
    for match in re.findall(r"https?://[^'\"\\s<>]+", html):
        if _looks_like_download(match):
            links.add(match)
    return sorted(links)


def discover(urls: list[str], *, timeout: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    headers = {"User-Agent": "OSINT-thesis-project/0.0.1 (academic)"}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for url in urls:
            result: dict[str, Any] = {"url": url, "downloads": []}
            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                result["error"] = str(exc)
            else:
                result["status_code"] = response.status_code
                result["final_url"] = str(response.url)
                content_type = response.headers.get("content-type", "")
                result["content_type"] = content_type
                if response.is_success and "text/html" in content_type:
                    result["downloads"] = extract_download_links(response.text, str(response.url))
            results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--write-manifest", type=Path)
    args = parser.parse_args()

    results = discover(ACLED_SOURCE_URLS, timeout=args.timeout)
    body = json.dumps(results, indent=2, sort_keys=True)
    print(body)
    if args.write_manifest:
        args.write_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.write_manifest.write_text(body + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
