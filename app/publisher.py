"""Who published this (#768).

A GDELT marker showed the machine-coded action `Coerce` and nothing else. The
worst half of that is already gone — #810 stopped drawing rows with no
headline — and what remains is the half a reader needs most: an RSS row names
an accountable owner, a GDELT row named nobody, while carrying in its payload
the URL that says exactly who.

Every one of the 16,128 titled GDELT rows in the last seven days carries a
`source_url`, so this is answerable for every row that can reach a map.

## Why a domain and not a masthead

`postbulletin.com`, not "Post Bulletin". A hand-written domain-to-name table
goes stale silently and starts inventing publishers for domains it half
recognises, which is the overclaim this issue exists to remove. A domain is
also checkable by the reader: they can go and look.

Feeds are different and are left alone. `rss_feeds.json` already declares a
pretty name and an owner for every feed, arrived at deliberately, and deriving
a domain for those would be a second and worse answer to a question that is
already answered.

A sensor has no publisher at all. Nobody published an earthquake.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

#: Prefixes that describe how a page is being served rather than who serves
#: it. `news.stv.tv` is a real desk and is kept; `m.` and `amp.` are transport.
_TRANSPORT_PREFIXES: tuple[str, ...] = ("www.", "m.", "amp.")


@lru_cache(maxsize=1)
def _feed_names() -> dict[str, str]:
    from app.sources.rss_registry import load_feed_configs

    return {config.source: config.pretty_name for config in load_feed_configs()}


def domain_of(url: str | None) -> str | None:
    """The registrable host of `url`, or None when there is not one.

    GDELT payloads written before #733 carry a 14-digit timestamp in this
    field rather than a URL, so "looks like a string" is not enough of a test.
    """
    if not isinstance(url, str) or "://" not in url:
        return None
    host = urlsplit(url.strip()).hostname
    if not host or "." not in host:
        return None
    host = host.lower()
    changed = True
    while changed:
        changed = False
        for prefix in _TRANSPORT_PREFIXES:
            if host.startswith(prefix) and host.count(".") > 1:
                host = host[len(prefix) :]
                changed = True
    return host or None


def publisher_for(source: str, payload: dict[str, Any] | None) -> str | None:
    """Who to credit on a row, or None when nobody published it."""
    if source.startswith("rss-"):
        return _feed_names().get(source)
    if source != "gdelt":
        return None
    return domain_of((payload or {}).get("source_url"))
