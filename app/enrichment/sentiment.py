"""News-headline sentiment scoring.

v1 uses VADER (Valence Aware Dictionary and sEntiment Reasoner) — a
lexicon + rule-based scorer. Pros: ~200 KB lexicon ships in-process, no
GPU, no model download, no torch dep, deterministic. Cons: tuned for
social media so financial / hard-news idioms can miss. The downstream
impact-score formula uses ``|sentiment|`` so a near-zero VADER reading
on a borderline headline only fails to amplify the row — it does not
generate a false signal.

Methodology version is stamped on every enriched row so the model
substitution path (issue #126b — distilbert NER + a transformer-based
sentiment model) keeps history reproducible.

References:
- Hutto, C.J. & Gilbert, E.E. (2014). VADER: A Parsimonious Rule-based
  Model for Sentiment Analysis of Social Media Text. ICWSM-14.
- NIP repo (BasilSuhail/news-intelligence-platform), Enrichment layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

#: Bumped together with any change to model or weights. Never edit a prior
#: version in place. The next bump (vader.v2.0 or transformer.v1.0) lands
#: with the BERT swap follow-up to #126.
SENTIMENT_METHOD_VERSION: str = "vader.v1.0"


@dataclass(frozen=True)
class SentimentHit:
    """Output of one sentiment score.

    ``compound`` is the headline-level scalar in [-1, 1] used downstream.
    ``label`` is a convenience bucket so the UI can chip-colour without
    re-deriving the threshold every time.
    """

    compound: float
    label: str
    method_version: str = SENTIMENT_METHOD_VERSION


def _label(compound: float) -> str:
    """VADER's published cut-offs for the compound score."""
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


@lru_cache(maxsize=1)
def _analyzer() -> SentimentIntensityAnalyzer:
    """Single shared analyzer — VADER is stateless after init.

    The lexicon load is a few ms on cold start; lru_cache avoids paying it
    on every fetcher tick.
    """
    return SentimentIntensityAnalyzer()


@lru_cache(maxsize=8192)
def score_text(text: str) -> SentimentHit | None:
    """Score one headline / summary string. Returns None on empty input.

    The lru_cache is shared by the fetcher (one new headline per tick) and
    the backfill script (one pass over historic rows), so repeated runs
    over the same text are a cache hit even across calls.
    """
    if not text or not text.strip():
        return None
    scores = _analyzer().polarity_scores(text)
    compound = float(scores.get("compound", 0.0))
    return SentimentHit(compound=compound, label=_label(compound))
