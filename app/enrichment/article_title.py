"""The headline a GDELT row is actually about (#788).

GDELT's export carries no headline. It carries a CAMEO root code — 17, 19,
20 — and the console printed that code's label where a headline belongs, so
a map selection read `Coerce · Edinburgh` four times in a row.

The label is not a summary of the article, and often not even related to it.
Sampled against the source URL's own slug:

    Coerce   community-first-credit-unions-1-million-pledge-brings-hope…
    Coerce   missing-boy-sparks-huge-rescue
    Assault  police-found-blood-on-jacket-nine-year-old-girl-was-wearing…

So no amount of rewording fixes it. Building "X coerces Y in Neenah" out of
the actor columns would state a falsehood more fluently than the bare word
does. The row has to carry what the article says, and the only place that
lives is the article.

What this module does not do: follow redirects to arbitrary depth, run
JavaScript, or read the body. It asks for the page, reads far enough to
reach the end of `<head>`, and takes the title.
"""

from __future__ import annotations

import contextlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final

import httpx

#: Long enough to reach `</head>` on a news page, short enough that a
#: misbehaving server cannot stream megabytes at the box. Measured against
#: the sources in the corpus: titles sit inside the first few KB, and the
#: outliers are ad-tech preambles that no larger cap would rescue.
MAX_BYTES: Final[int] = 64 * 1024

#: One connection, one short wait. A news site that cannot answer in this
#: time is not worth holding a slot for — the row keeps its fallback and
#: the next attempt is a whole beat away.
TIMEOUT_S: Final[float] = 6.0

#: Says who is asking. A blank or spoofed agent is how a well-behaved
#: fetcher gets mistaken for a badly-behaved one.
USER_AGENT: Final[str] = "osint-console/1.0 (+headline lookup for mapped events)"

#: Anything shorter is a placeholder ("News", "404"), anything longer is a
#: page that put its whole description in the title.
MIN_TITLE_LEN: Final[int] = 12
MAX_TITLE_LEN: Final[int] = 300

#: Trailing site branding: "Headline | The Guardian", "Headline - BBC News".
#: Only stripped when what remains is still a sentence, so a genuinely short
#: headline is never cut down to nothing. The separators are pipe, hyphen,
#: en dash and em dash, spelled as escapes because a bare en dash in source
#: is indistinguishable from a hyphen at a glance.
_SEPARATORS: Final[str] = "|\u2013\u2014-"
_BRANDING: Final[re.Pattern[str]] = re.compile(rf"\s*[{_SEPARATORS}]\s*[^{_SEPARATORS}]{{2,40}}$")

#: Pages that answer with a title but no article: consent walls, bot checks,
#: and the soft 404s that return 200. Matched case-folded against the whole
#: title, because "Are you a robot?" is not a headline about Edinburgh.
_NOT_A_HEADLINE: Final[frozenset[str]] = frozenset(
    {
        "access denied",
        "are you a robot",
        "attention required",
        "bot verification",
        "just a moment",
        "page not found",
        "access to this page has been denied",
        "please verify you are a human",
        "security check",
        "site maintenance",
        "subscribe to read",
        "403 forbidden",
        "404 not found",
        "error",
        "news",
        "home",
    }
)


@dataclass(frozen=True)
class TitleResult:
    """What a lookup found, and whether asking again could help.

    `retryable` is the load-bearing field. A timeout is worth another go on
    the next beat; a 404 is not, and a row that keeps asking a dead link
    forever is a beat that never reaches the live rows behind it.
    """

    title: str | None
    reason: str
    retryable: bool


class _HeadParser(HTMLParser):
    """Collects `og:title` and `<title>`, then stops at the end of `<head>`.

    `og:title` wins where both exist: it is the headline an outlet chose for
    sharing, without the site branding that `<title>` usually carries.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title: str | None = None
        self.doc_title: str | None = None
        self._in_title = False
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta" or self.og_title:
            return
        found = dict(attrs)
        key = (found.get("property") or found.get("name") or "").lower()
        if key in {"og:title", "twitter:title"}:
            content = (found.get("content") or "").strip()
            if content:
                self.og_title = content

    def handle_data(self, data: str) -> None:
        if not self._in_title:
            return
        self.doc_title = ((self.doc_title or "") + data)[: MAX_TITLE_LEN * 2]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True


def clean_title(raw: str | None) -> str | None:
    """A usable headline, or None when what came back is not one.

    Rejecting is the point. A consent wall's "Just a moment…" printed on the
    map would be worse than the CAMEO code it replaced, because it looks
    like a real headline.
    """
    if not raw:
        return None
    text = html.unescape(" ".join(raw.split())).strip()
    if not text:
        return None
    if text.casefold().strip(" .!?") in _NOT_A_HEADLINE:
        return None
    stripped = _BRANDING.sub("", text).strip()
    if len(stripped) >= MIN_TITLE_LEN:
        text = stripped
    if len(text) < MIN_TITLE_LEN or len(text) > MAX_TITLE_LEN:
        return None
    if text.casefold().strip(" .!?") in _NOT_A_HEADLINE:
        return None
    return text


def parse_title(body: str) -> str | None:
    """The headline out of an HTML head. Never raises on malformed markup."""
    parser = _HeadParser()
    #: A broken page is a miss, not a crash — HTMLParser raises on some
    #: malformed markup and whatever it collected before that is still good.
    with contextlib.suppress(Exception):
        parser.feed(body)
    return clean_title(parser.og_title) or clean_title(parser.doc_title)


def _body_prefix(response: httpx.Response) -> str:
    """Up to MAX_BYTES of the response, decoded as best the headers allow."""
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            break
    raw = b"".join(chunks)[:MAX_BYTES]
    return raw.decode(response.encoding or "utf-8", errors="replace")


def fetch_title(url: str, *, client: httpx.Client | None = None) -> TitleResult:
    """The article's own headline, or why there isn't one.

    Every failure is a `TitleResult`, never an exception: this runs over a
    batch, and one dead link must not end the batch.
    """
    if not url.lower().startswith(("http://", "https://")):
        return TitleResult(None, "not-a-url", retryable=False)

    owned = client is None
    http = client or httpx.Client(
        timeout=TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with http.stream("GET", url) as response:
            if response.status_code >= 400:
                #: 429 and 5xx are the site having a moment; 404 and 410 are
                #: the article being gone, and asking again cannot change it.
                retryable = response.status_code == 429 or response.status_code >= 500
                return TitleResult(None, f"http-{response.status_code}", retryable=retryable)
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower():
                return TitleResult(None, "not-html", retryable=False)
            title = parse_title(_body_prefix(response))
        return (
            TitleResult(title, "ok", retryable=False)
            if title
            else TitleResult(None, "no-title", retryable=False)
        )
    except httpx.TimeoutException:
        return TitleResult(None, "timeout", retryable=True)
    except httpx.HTTPError as exc:
        return TitleResult(None, f"transport:{type(exc).__name__}", retryable=True)
    finally:
        if owned:
            http.close()
