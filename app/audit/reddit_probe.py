"""Does a resident report a thing before the wire does? (#804)

A read-only measurement of city subreddits. It writes nothing to `events`,
creates no source, and produces no row that could ever count toward
`owner_count` — one pseudonymous author is not an independent organisation,
and letting one corroborate would put the least accountable input into the
number that exists to say how much to believe something.

## What was already measured, and is therefore not measured again

A first pass on 2026-08-06/07 answered three of the five unknowns in #804
from a handful of paced requests:

- **Volume.** Each `.rss` entry carries its timestamp, so the span of the 25
  newest gives posts per day directly. Edinburgh 25.8, Manchester 23.4,
  Lahore 21.1, berlin 11.1, Nairobi 7.1, Cairo 131.4.
- **Signal.** Hand-labelled, roughly 3 of 25 carry ground-level incident
  value in anglophone UK cities, and 0 of 25 in Lahore and Cairo.
- **Reachability.** 9 of 16 anonymous requests succeeded at 12-45 second
  spacing; the rest answered 429 with `x-ratelimit-remaining: 0`.

## What is left, and what this measures

**Latency.** The early-signal claim is that a resident posts before the wire
carries it. Nobody has timed it. This matches each post against stored
`events` rows by title tokens and reports the signed difference in minutes:
negative means Reddit was first.

**Native versus repost.** The strongest Edinburgh post in the first pass was
a link to a local newsroom — tier-one content arriving second-hand without
its owner. The share that is a link rather than a resident's own words
decides whether the tier is a source or an echo.

**Variance.** One pull is one day. Re-running this over a week separates a
festival from a February.

## Constraints this holds to

Serial, paced, one request at a time, backoff on 429, an identifying
User-Agent. Reddit's public content policy restricts bulk use, and the
`.rss` endpoints being reachable is not the same as unrestricted — this is a
measurement of five subreddits, run on demand, not a continuous collector.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.stories.vectorize import tokenize

ATOM: Final[str] = "{http://www.w3.org/2005/Atom}"

#: Identifies the caller. An anonymous scraper with a browser string is the
#: thing the policy is written against.
USER_AGENT: Final[str] = "osint-research-probe/0.1 (read-only measurement, five subreddits)"

#: Chosen to span the story rather than to look good: two cities where local
#: newsrooms now feed the corpus (#805), two where none could be found at all,
#: and one that does not post in English.
PROBE_SUBREDDITS: Final[tuple[str, ...]] = (
    "Edinburgh",
    "Manchester",
    "Nairobi",
    "Cairo",
    "berlin",
)

#: Anonymous Reddit allows roughly one request per ten seconds, and answered
#: 429 to 7 of 16 requests spaced 12-45 seconds apart. Slower than the headers
#: suggest, because the headers describe the budget rather than the queue.
REQUEST_SPACING_SECONDS: Final[float] = 20.0

#: How long to wait after a 429 that carries no `retry-after`.
BACKOFF_SECONDS: Final[float] = 60.0

MAX_ATTEMPTS: Final[int] = 3

#: Token overlap two headlines need before they are called the same story.
#: Deliberately blunt: this asks "did the corpus already have this", and a
#: threshold tuned until the answer flattered the claim would be worthless.
MATCH_THRESHOLD: Final[float] = 0.5

#: How far either side of a post to look for its twin. A story the corpus
#: carried three days earlier is not the same telling.
MATCH_WINDOW_HOURS: Final[int] = 48

_REDDIT_HOSTS: Final[tuple[str, ...]] = ("reddit.com", "redd.it")
_HREF_RE: Final[re.Pattern[str]] = re.compile(r'href="(https?://[^"]+)"')


@dataclass(frozen=True)
class RedditPost:
    """One entry from a subreddit's `.rss` feed."""

    subreddit: str
    post_id: str
    title: str
    posted_at: datetime
    #: The outbound article a link post points at, or None for a self-post.
    external_url: str | None

    @property
    def is_link_post(self) -> bool:
        return self.external_url is not None


@dataclass(frozen=True)
class Match:
    """A post and the stored row that tells the same story."""

    post: RedditPost
    event_source: str
    event_title: str
    #: Post time minus row time. Negative means Reddit carried it first.
    lead_minutes: float


@dataclass
class SubredditProbe:
    subreddit: str
    posts: list[RedditPost] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    #: HTTP status when the pull failed, or None when it worked.
    failed_with: int | None = None

    @property
    def span_hours(self) -> float:
        if len(self.posts) < 2:
            return 0.0
        stamps = sorted(p.posted_at for p in self.posts)
        return (stamps[-1] - stamps[0]).total_seconds() / 3600

    @property
    def posts_per_day(self) -> float | None:
        span = self.span_hours
        return (len(self.posts) - 1) / span * 24 if span else None

    @property
    def link_posts(self) -> int:
        return sum(1 for p in self.posts if p.is_link_post)

    @property
    def median_lead_minutes(self) -> float | None:
        if not self.matches:
            return None
        leads = sorted(m.lead_minutes for m in self.matches)
        mid = len(leads) // 2
        return leads[mid] if len(leads) % 2 else (leads[mid - 1] + leads[mid]) / 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "subreddit": self.subreddit,
            "posts": len(self.posts),
            "span_hours": round(self.span_hours, 2),
            "posts_per_day": self.posts_per_day,
            "link_posts": self.link_posts,
            "matched": len(self.matches),
            "median_lead_minutes": self.median_lead_minutes,
            "failed_with": self.failed_with,
        }


def parse_feed(xml: str, *, subreddit: str) -> list[RedditPost]:
    """Atom entries → posts. Pure, so the parsing rules are testable."""
    root = ElementTree.fromstring(xml)
    posts: list[RedditPost] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        stamp = entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")
        post_id = (entry.findtext(f"{ATOM}id") or "").strip()
        if not title or not stamp:
            continue
        try:
            posted_at = datetime.fromisoformat(stamp).astimezone(UTC)
        except ValueError:
            continue
        content = entry.findtext(f"{ATOM}content") or ""
        posts.append(
            RedditPost(
                subreddit=subreddit,
                post_id=post_id,
                title=title,
                posted_at=posted_at,
                external_url=external_link(content),
            )
        )
    return posts


def external_link(content_html: str) -> str | None:
    """The outbound article a link post points at, if it is one.

    A self-post's content links only back to Reddit. Anything else is the
    post carrying somebody else's reporting, which makes it an echo of a
    source the corpus may already have rather than a resident's own account.
    """
    for url in _HREF_RE.findall(content_html):
        if not any(host in url for host in _REDDIT_HOSTS):
            return url
    return None


def match_to_events(
    session: Session,
    posts: list[RedditPost],
    *,
    threshold: float = MATCH_THRESHOLD,
    window_hours: int = MATCH_WINDOW_HOURS,
) -> list[Match]:
    """Posts whose story the corpus already carries, with the time difference.

    Token overlap on the headline, using the same tokenizer story clustering
    uses, so "the corpus already had this" means the same thing here as it
    does there.
    """
    if not posts:
        return []
    window = _timedelta_hours(window_hours)
    earliest = min(p.posted_at for p in posts) - window
    latest = max(p.posted_at for p in posts) + window

    rows = session.execute(
        select(EventRow.source, EventRow.occurred_at, EventRow.payload).where(
            EventRow.occurred_at >= earliest,
            EventRow.occurred_at <= latest,
        )
    ).all()

    candidates: list[tuple[str, datetime, str, set[str]]] = []
    for source, occurred_at, payload in rows:
        title = (payload or {}).get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        tokens = set(tokenize(title))
        if tokens:
            candidates.append((source, _as_utc(occurred_at), title, tokens))

    matches: list[Match] = []
    for post in posts:
        post_tokens = set(tokenize(post.title))
        if not post_tokens:
            continue
        best: tuple[float, str, str, datetime] | None = None
        for source, occurred_at, title, tokens in candidates:
            overlap = len(post_tokens & tokens) / len(post_tokens | tokens)
            if overlap < threshold:
                continue
            if abs((post.posted_at - occurred_at).total_seconds()) > window.total_seconds():
                continue
            if best is None or overlap > best[0]:
                best = (overlap, source, title, occurred_at)
        if best is not None:
            _, source, title, occurred_at = best
            matches.append(
                Match(
                    post=post,
                    event_source=source,
                    event_title=title,
                    lead_minutes=(post.posted_at - occurred_at).total_seconds() / 60,
                )
            )
    return matches


def fetch_feed(subreddit: str, *, client: httpx.Client, sleep=time.sleep) -> tuple[str | None, int]:
    """One subreddit's Atom feed, paced and backing off on 429.

    Returns the body and the final status. `sleep` is injected so the retry
    behaviour can be tested without spending a minute on it.
    """
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
    status = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.get(url, headers={"User-Agent": USER_AGENT})
        status = response.status_code
        if status == 200:
            return response.text, status
        if status != 429 or attempt == MAX_ATTEMPTS:
            return None, status
        sleep(_retry_after(response) or BACKOFF_SECONDS * attempt)
    return None, status


def probe(
    session: Session,
    *,
    subreddits: tuple[str, ...] = PROBE_SUBREDDITS,
    client: httpx.Client | None = None,
    sleep=time.sleep,
) -> list[SubredditProbe]:
    """Pull each subreddit in turn, match against stored rows, report."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    results: list[SubredditProbe] = []
    try:
        for index, subreddit in enumerate(subreddits):
            if index:
                sleep(REQUEST_SPACING_SECONDS)
            body, status = fetch_feed(subreddit, client=client, sleep=sleep)
            if body is None:
                results.append(SubredditProbe(subreddit=subreddit, failed_with=status))
                continue
            posts = parse_feed(body, subreddit=subreddit)
            results.append(
                SubredditProbe(
                    subreddit=subreddit,
                    posts=posts,
                    matches=match_to_events(session, posts),
                )
            )
    finally:
        if owns_client:
            client.close()
    return results


def format_report(probes: list[SubredditProbe]) -> str:
    """A table, and no verdict. The numbers are the finding."""
    head = (
        f"{'subreddit':<14}{'posts':>7}{'span_h':>8}{'per_day':>9}"
        f"{'links':>7}{'matched':>9}{'lead_min':>10}"
    )
    lines = [head, "-" * len(head)]
    for probe_result in probes:
        if probe_result.failed_with is not None:
            failed = f"HTTP {probe_result.failed_with}"
            lines.append(f"{probe_result.subreddit:<14}{failed:>7}")
            continue
        per_day = probe_result.posts_per_day
        lead = probe_result.median_lead_minutes
        lines.append(
            f"{probe_result.subreddit:<14}{len(probe_result.posts):>7}"
            f"{probe_result.span_hours:>8.1f}{per_day if per_day else 0:>9.1f}"
            f"{probe_result.link_posts:>7}{len(probe_result.matches):>9}"
            f"{'-' if lead is None else format(lead, '.0f'):>10}"
        )
    lines.append("")
    lines.append("lead_min is post time minus stored row time: negative means Reddit was first.")
    return "\n".join(lines)


def write_jsonl(probes: list[SubredditProbe], path) -> int:
    """Raw posts to disk, never to `events`. Returns rows written."""
    written = 0
    with open(path, "w", encoding="utf-8") as handle:
        for probe_result in probes:
            leads = {m.post.post_id: m for m in probe_result.matches}
            for post in probe_result.posts:
                match = leads.get(post.post_id)
                handle.write(
                    json.dumps(
                        {
                            "subreddit": post.subreddit,
                            "post_id": post.post_id,
                            "title": post.title,
                            "posted_at": post.posted_at.isoformat(),
                            "external_url": post.external_url,
                            "matched_source": match.event_source if match else None,
                            "lead_minutes": match.lead_minutes if match else None,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                written += 1
    return written


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timedelta_hours(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)


def main() -> int:
    """`python -m app.audit.reddit_probe` — run it and print the table.

    On demand, never on a schedule. A continuous collector is the thing #804
    says to size before building, and this is the sizing.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.paths import exports_dir
    from app.settings import settings

    engine = create_engine(settings.postgres_url)
    with sessionmaker(bind=engine)() as session:
        probes = probe(session)
    print(format_report(probes))

    out = exports_dir() / f"reddit-probe-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
    written = write_jsonl(probes, out)
    print(f"\n{written} posts written to {out} — nothing was written to events.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
