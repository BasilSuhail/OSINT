"""Browser-assisted ACLED download capture.

This script is for myACLED pages that hide downloads behind a logged-in browser
session. It stores the browser profile and downloaded files under gitignored
``data/private/acled/`` paths and never stores credentials in code or env files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.acled_discover import ACLED_SOURCE_URLS, extract_download_links

PRIVATE_ROOT = Path("data/private/acled")
DEFAULT_PROFILE_DIR = PRIVATE_ROOT / "browser-profile"
DEFAULT_DOWNLOAD_DIR = PRIVATE_ROOT
DEFAULT_MANIFEST_PATH = PRIVATE_ROOT / "browser-sync-manifest.json"
DOWNLOAD_TEXT_RE = re.compile(r"\b(download|csv|excel|xlsx|export)\b", re.IGNORECASE)
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class BrowserSyncConfig:
    urls: list[str]
    profile_dir: Path = DEFAULT_PROFILE_DIR
    download_dir: Path = DEFAULT_DOWNLOAD_DIR
    manifest_path: Path = DEFAULT_MANIFEST_PATH
    headless: bool = False
    login: bool = False
    max_clicks_per_page: int = 8
    page_timeout_ms: int = 30_000
    download_timeout_ms: int = 8_000


def resolve_private_path(path: Path, *, root: Path = PRIVATE_ROOT) -> Path:
    root_abs = root.resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root_abs)
    except ValueError as exc:
        raise ValueError(f"path must stay under {root}") from exc
    return resolved


def safe_download_name(raw_name: str, *, fallback_url: str, index: int) -> str:
    name = raw_name.strip()
    if not name:
        url_path = Path(urlparse(fallback_url).path)
        name = url_path.name
    if not name:
        name = f"acled-download-{index}.csv"
    cleaned = SAFE_FILENAME_RE.sub("_", name).strip("._-")
    return cleaned or f"acled-download-{index}.csv"


def build_config(args: argparse.Namespace) -> BrowserSyncConfig:
    return BrowserSyncConfig(
        urls=args.url or ACLED_SOURCE_URLS,
        profile_dir=Path(args.profile_dir),
        download_dir=Path(args.download_dir),
        manifest_path=Path(args.manifest_path),
        headless=args.headless,
        login=args.login,
        max_clicks_per_page=args.max_clicks_per_page,
        page_timeout_ms=args.page_timeout_ms,
        download_timeout_ms=args.download_timeout_ms,
    )


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: "
            "pip install -e '.[browser]' && python -m playwright install chromium"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def _save_download(download: Any, *, config: BrowserSyncConfig, url: str, index: int) -> str:
    raw_name = download.suggested_filename or ""
    filename = safe_download_name(raw_name, fallback_url=url, index=index)
    destination = resolve_private_path(config.download_dir / filename)
    suffix = destination.suffix
    stem = destination.stem
    counter = 1
    while destination.exists():
        destination = resolve_private_path(destination.with_name(f"{stem}-{counter}{suffix}"))
        counter += 1
    download.save_as(str(destination))
    return str(destination)


def _visible_download_controls(page: Any, *, limit: int) -> list[Any]:
    controls = page.locator("a, button, [role=button]").all()
    out: list[Any] = []
    for control in controls:
        if len(out) >= limit:
            break
        try:
            if not control.is_visible():
                continue
            label = control.inner_text(timeout=500).strip()
        except Exception:
            continue
        if DOWNLOAD_TEXT_RE.search(label):
            out.append(control)
    return out


def run_browser_sync(config: BrowserSyncConfig) -> list[dict[str, Any]]:
    profile_dir = resolve_private_path(config.profile_dir)
    download_dir = resolve_private_path(config.download_dir)
    manifest_path = resolve_private_path(config.manifest_path)
    profile_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    sync_playwright, playwright_timeout = _load_playwright()
    results: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir),
            accept_downloads=True,
            downloads_path=str(download_dir),
            headless=config.headless,
        )
        page = context.new_page()
        page.set_default_timeout(config.page_timeout_ms)

        if config.login:
            page.goto("https://acleddata.com/myacled", wait_until="domcontentloaded")
            input("Log into myACLED in the opened browser, then press Enter here...")

        for url in config.urls:
            result: dict[str, Any] = {"url": url, "direct_links": [], "saved_downloads": []}
            try:
                response = page.goto(url, wait_until="domcontentloaded")
                result["status_code"] = response.status if response else None
                result["final_url"] = page.url
                result["direct_links"] = extract_download_links(page.content(), page.url)

                controls = _visible_download_controls(page, limit=config.max_clicks_per_page)
                result["download_controls"] = len(controls)
                for index, control in enumerate(controls, start=1):
                    try:
                        with page.expect_download(timeout=config.download_timeout_ms) as dl_info:
                            control.click()
                        saved = _save_download(
                            dl_info.value,
                            config=config,
                            url=url,
                            index=index,
                        )
                    except playwright_timeout:
                        continue
                    result["saved_downloads"].append(saved)
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)

        context.close()

    manifest_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", help="ACLED page URL. Defaults to known pages.")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--download-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--max-clicks-per-page", type=int, default=8)
    parser.add_argument("--page-timeout-ms", type=int, default=30_000)
    parser.add_argument("--download-timeout-ms", type=int, default=8_000)
    parser.add_argument("--print-config", action="store_true")
    args = parser.parse_args()

    config = build_config(args)
    if args.print_config:
        print(json.dumps(asdict(config), indent=2, sort_keys=True, default=str))
        return

    try:
        results = run_browser_sync(config)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
