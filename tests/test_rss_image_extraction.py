"""Tests for ``app.sources.rss_news_fetcher._extract_image_url``.

Covers the four extraction strategies the function walks in order:
media:thumbnail (BBC), media:content (Reuters / Guardian), enclosure
(Dawn / Geo), and the HTML <img> fallback.
"""

from __future__ import annotations

from app.sources.rss_news_fetcher import _extract_image_url


def test_returns_none_when_entry_is_empty() -> None:
    assert _extract_image_url({}, "") is None


def test_media_thumbnail_takes_priority() -> None:
    entry = {
        "media_thumbnail": [{"url": "https://example.com/thumb.jpg", "width": "240"}],
    }
    assert _extract_image_url(entry, "") == "https://example.com/thumb.jpg"


def test_media_content_used_when_no_thumbnail() -> None:
    entry = {
        "media_content": [{"url": "https://example.com/full.jpg", "type": "image/jpeg"}],
    }
    assert _extract_image_url(entry, "") == "https://example.com/full.jpg"


def test_media_content_skipped_when_non_image_type() -> None:
    entry = {
        "media_content": [{"url": "https://example.com/clip.mp4", "type": "video/mp4"}],
    }
    assert _extract_image_url(entry, "") is None


def test_enclosure_used_when_no_media() -> None:
    entry = {
        "links": [
            {"rel": "alternate", "href": "https://example.com/article"},
            {"rel": "enclosure", "href": "https://example.com/hero.jpg", "type": "image/jpeg"},
        ],
    }
    assert _extract_image_url(entry, "") == "https://example.com/hero.jpg"


def test_html_img_used_as_last_resort() -> None:
    html = '<p>Some text</p><img src="https://example.com/inline.png" alt="x"/>'
    assert _extract_image_url({}, html) == "https://example.com/inline.png"


def test_first_html_img_wins_when_many() -> None:
    html = '<img src="https://example.com/first.png"/><img src="https://example.com/second.png"/>'
    assert _extract_image_url({}, html) == "https://example.com/first.png"


def test_priority_order_thumbnail_beats_html() -> None:
    entry = {
        "media_thumbnail": [{"url": "https://example.com/thumb.jpg"}],
    }
    html = '<img src="https://example.com/inline.png"/>'
    assert _extract_image_url(entry, html) == "https://example.com/thumb.jpg"
