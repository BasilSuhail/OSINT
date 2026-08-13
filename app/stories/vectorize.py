"""Vectorize layer — headline → tf-idf token vector, cosine similarity.

Pure functions, dict-based sparse vectors. Titles are short so tf is
effectively binary.

Idf demotes a token that is *common in the window*, which is not the same as
demoting boilerplate: a stock phrase used a few times a week is rare enough to
score as highly distinctive, and smoothing floors every weight at 1.0 besides.
Formula words are therefore removed by name in the stopword list below rather
than left for idf to handle, because idf measurably does not (#913).

Calendar words go the same way and for the same reason (#950). A date says
when a piece was filed, never what happened in it, and a recurring column is a
fixed phrase whose only moving part is the date — so a month and a year are
precisely the tokens that let one column's daily editions find each other.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Small builtin stopword list — enough to strip glue words from headlines.
_STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "he",
        "her",
        "his",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "after",
        "amid",
        "over",
        "under",
        "says",
        "said",
        "say",
        "new",
        "live",
        "update",
        "updates",
        "breaking",
        "report",
        "reports",
        #: Names of recurring columns rather than words about the world (#890).
        #: An outlet's daily edition is called the same thing every day, so
        #: these tokens describe the slot a piece was published in, never what
        #: happened in it.
        "recap",
        "roundup",
        "briefing",
        "digest",
        "latest",
        #: The explainer formula (#913). "What we know so far" ran on eight
        #: headlines of a 6,561-headline window, so document frequency read it
        #: as one of the most discriminating things in the corpus — `know`
        #: weighed 7.016 against `earthquake` at 5.897. Two explainers about
        #: unrelated events then matched on the heaviest tokens either of them
        #: had, and one story collected a football tournament, a Berlin attack,
        #: two Japanese earthquakes and Iraqi militias.
        #:
        #: These belong here for the same reason the words above do: they name
        #: the shape of a piece, never its subject. Deliberately only three.
        #: `far` is half of "far right", `learn` is a verb about the world, and
        #: `who` is a health agency as often as it is a pronoun — all three were
        #: measured and none is needed, because the formula cannot reach the two
        #: shared tokens a join requires without these.
        "what",
        "know",
        "about",
        #: The publication slot (#950). `recap` and `briefing` above name the
        #: shape of a piece; these name the hour it went out in, which is the
        #: same kind of nothing. An outlet files a bulletin headed with the
        #: date and the slot three times a day, and with `latest` already
        #: boilerplate the headline still carried `news`, `bulletin` and
        #: `evening` — enough to clear the two-token bar and enough to match
        #: every other edition, so one column became a 94-filing "story"
        #: spanning thirty days.
        "bulletin",
        "edition",
        "headlines",
        "morning",
        "midday",
        "afternoon",
        "evening",
        "tonight",
        "today",
        "yesterday",
        "tomorrow",
        "weekend",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
)

#: Month names, long and short. A date says when a piece was filed, never what
#: happened in it, and a recurring column is a fixed phrase whose only moving
#: part is the date (#950).
_MONTHS: frozenset[str] = frozenset(
    [
        "january",
        "february",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "apr",
        "jun",
        "jul",
        "aug",
        "sept",
        "oct",
        "nov",
        "dec",
        #: `may`, `march` and `mar` are deliberately absent. Each is an
        #: ordinary English word before it is a date — people may act, crowds
        #: march — and dropping them would take meaning out of headlines that
        #: carry no date at all. No recurring column needs them to be caught:
        #: the ones measured here are named by month and year together, and
        #: every other month still goes.
    ]
)

#: Ordinal day-of-month forms: 1st … 31st. Written out rather than matched by
#: pattern so that `21st` goes and a name like `21st Century Fox` keeps the
#: rest of its words to stand on.
_ORDINAL_DAYS: frozenset[str] = frozenset(
    f"{day}{suffix}" for day in range(1, 32) for suffix in ("st", "nd", "rd", "th")
)

_MIN_TOKEN_LEN = 3


def _is_year(token: str) -> bool:
    """A plausible four-digit calendar year, which dates a piece rather than
    describing it. Bounded so a casualty figure like `1500` is not mistaken
    for one — and it is bounded low enough that `2026` is caught."""
    return len(token) == 4 and token.isdigit() and "1900" <= token <= "2099"


def _is_calendar(token: str) -> bool:
    return token in _MONTHS or token in _ORDINAL_DAYS or _is_year(token)


def tokenize(title: str) -> list[str]:
    """Lowercase alphanumeric tokens; stopwords, calendar words and short
    tokens dropped."""
    return [
        token
        for token in _TOKEN_RE.findall(title.lower())
        if token not in _STOPWORDS and len(token) >= _MIN_TOKEN_LEN and not _is_calendar(token)
    ]


def build_idf(documents: Iterable[list[str]]) -> dict[str, float]:
    """Smoothed idf: ln(N / df) + 1 over tokenized documents."""
    docs = list(documents)
    if not docs:
        return {}
    df: Counter[str] = Counter()
    for tokens in docs:
        df.update(set(tokens))
    n = len(docs)
    return {token: math.log(n / count) + 1.0 for token, count in df.items()}


def vectorize(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """tf-idf sparse vector; unseen tokens get idf 1.0 (neutral)."""
    counts = Counter(tokens)
    return {token: count * idf.get(token, 1.0) for token, count in counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between sparse vectors; 0.0 when either is empty."""
    if not a or not b:
        return 0.0
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(weight * large.get(token, 0.0) for token, weight in small.items())
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    return dot / (norm_a * norm_b)
