"""Tests for browser-assisted ACLED download helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.acled_browser_sync import (
    PRIVATE_ROOT,
    BrowserSyncConfig,
    build_config,
    resolve_private_path,
    safe_download_name,
)


def test_resolve_private_path_accepts_private_acled_paths() -> None:
    resolved = resolve_private_path(PRIVATE_ROOT / "browser-profile")
    assert resolved.name == "browser-profile"
    assert (PRIVATE_ROOT.resolve()) in resolved.parents


def test_resolve_private_path_rejects_paths_outside_private_acled() -> None:
    with pytest.raises(ValueError):
        resolve_private_path(Path("data/private/other"))


def test_safe_download_name_uses_suggested_name() -> None:
    assert (
        safe_download_name(
            "ACLED Export June 2026.csv",
            fallback_url="https://example.test",
            index=1,
        )
        == "ACLED_Export_June_2026.csv"
    )


def test_safe_download_name_uses_url_fallback() -> None:
    assert (
        safe_download_name("", fallback_url="https://example.test/downloads/acled.xlsx", index=2)
        == "acled.xlsx"
    )


def test_build_config_defaults_to_private_paths() -> None:
    class Args:
        url = None
        profile_dir = "data/private/acled/browser-profile"
        download_dir = "data/private/acled"
        manifest_path = "data/private/acled/browser-sync-manifest.json"
        headless = True
        login = False
        max_clicks_per_page = 3
        page_timeout_ms = 1000
        download_timeout_ms = 500

    config = build_config(Args())

    assert isinstance(config, BrowserSyncConfig)
    assert config.headless is True
    assert config.max_clicks_per_page == 3
    assert config.profile_dir == Path("data/private/acled/browser-profile")
