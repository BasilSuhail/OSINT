"""Does the bloc tone signal carry anything, and is VADER right about it (#639)?

Baseline for #155, which cannot be decided without a number. Two questions, and
the first one can invalidate the second.

**Does tone discriminate between blocs at all?** `_tone_lean` presents VADER's
label as "a bloc's emotional lean", but VADER measures the valence of a piece of
text, not an outlet's stance. Two blocs reporting the same massacre both produce
negative valence whatever their politics. If blocs almost never disagree on a
shared story, the feature carries no signal *regardless of which model produces
the label*, and #155's model swap fixes nothing.

**Is VADER right on hard news?** Its own authors evaluate four corpora, and news
editorials score lowest of the four — it is a social-media lexicon pointed at a
hard-news feed. Nothing here has ever checked.

Pure functions. The script does the I/O; this does the arithmetic, so the
statistics are testable without a database or a model.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

#: The buckets VADER emits and `_tone_lean` consumes.
TONE_LABELS: tuple[str, ...] = ("negative", "neutral", "positive")

#: A story needs at least this many blocs before "do they disagree" is a
#: question. One bloc cannot disagree with itself.
MIN_BLOCS: int = 2

#: A bloc needs at least this many labelled articles in a story before its lean
#: means anything. One article is an anecdote, not a lean.
MIN_ARTICLES_PER_BLOC: int = 2


@dataclass(frozen=True)
class Member:
    """One story member, reduced to what the measurement needs."""

    story_id: int
    origin_country: str
    label: str | None


def dominant_label(labels: Sequence[str]) -> str | None:
    """The most common label, or None on a tie or an empty input.

    A tie is reported as no lean rather than broken arbitrarily: the point of
    the measurement is whether blocs differ, and inventing a winner from a 3-3
    split would manufacture exactly the disagreement being counted.
    """
    usable = [label for label in labels if label in TONE_LABELS]
    if not usable:
        return None
    counts = Counter(usable).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    return counts[0][0]


@dataclass(frozen=True)
class StoryLeans:
    """Per-bloc leans within one story."""

    story_id: int
    leans: dict[str, str]

    @property
    def blocs(self) -> int:
        return len(self.leans)

    @property
    def unanimous(self) -> bool:
        """True when every bloc landed on the same lean."""
        return len(set(self.leans.values())) == 1


@dataclass(frozen=True)
class DiscriminationReport:
    """Part A — does tone vary between blocs on the same story?"""

    stories_considered: int = 0
    stories_unanimous: int = 0
    #: Stories dropped for having too few blocs or too few labelled articles.
    stories_skipped: int = 0
    #: How often each lean is emitted overall.
    label_counts: dict[str, int] = field(default_factory=dict)
    #: Per bloc, how its lean is distributed across the stories it appears in.
    per_bloc: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def unanimous_share(self) -> float | None:
        """Share of multi-bloc stories where nobody disagreed.

        Near 1.0 means the feature is decorative: it says the same thing about
        every bloc, so comparing blocs on it tells a reader nothing.
        """
        if self.stories_considered == 0:
            return None
        return self.stories_unanimous / self.stories_considered


def measure_discrimination(
    members: Iterable[Member],
    *,
    min_blocs: int = MIN_BLOCS,
    min_articles_per_bloc: int = MIN_ARTICLES_PER_BLOC,
) -> DiscriminationReport:
    """Part A. Needs no model — it reads labels already stored."""
    by_story: dict[int, dict[str, list[str]]] = {}
    for member in members:
        if member.label not in TONE_LABELS:
            continue
        by_story.setdefault(member.story_id, {}).setdefault(member.origin_country, []).append(
            member.label
        )

    considered = 0
    unanimous = 0
    skipped = 0
    label_counts: Counter[str] = Counter()
    per_bloc: dict[str, Counter[str]] = {}

    for story_id, blocs in by_story.items():
        leans: dict[str, str] = {}
        for country, labels in blocs.items():
            if len(labels) < min_articles_per_bloc:
                continue
            lean = dominant_label(labels)
            if lean is not None:
                leans[country] = lean

        if len(leans) < min_blocs:
            skipped += 1
            continue

        story = StoryLeans(story_id=story_id, leans=leans)
        considered += 1
        if story.unanimous:
            unanimous += 1
        for country, lean in leans.items():
            label_counts[lean] += 1
            per_bloc.setdefault(country, Counter())[lean] += 1

    return DiscriminationReport(
        stories_considered=considered,
        stories_unanimous=unanimous,
        stories_skipped=skipped,
        label_counts=dict(label_counts),
        per_bloc={country: dict(counts) for country, counts in per_bloc.items()},
    )


@dataclass(frozen=True)
class Disagreement:
    """One headline the two scorers labelled differently."""

    headline: str
    vader: str
    model: str


@dataclass(frozen=True)
class AgreementReport:
    """Part B — how often VADER and the model say the same thing."""

    compared: int = 0
    agreed: int = 0
    #: Rows the model could not label. Reported rather than dropped silently:
    #: a model that refuses half the corpus is a finding, not a footnote.
    unscored: int = 0
    #: {(vader, model): count} — the confusion matrix, as a flat mapping.
    confusion: dict[tuple[str, str], int] = field(default_factory=dict)
    disagreements: tuple[Disagreement, ...] = ()

    @property
    def agreement(self) -> float | None:
        if self.compared == 0:
            return None
        return self.agreed / self.compared

    def confusion_row(self, vader_label: str) -> dict[str, int]:
        """What the model said, for every row VADER called `vader_label`."""
        return {
            model: count
            for (stored, model), count in self.confusion.items()
            if stored == vader_label
        }


def measure_agreement(
    pairs: Iterable[tuple[str, str, str | None]],
    *,
    max_examples: int = 40,
) -> AgreementReport:
    """Part B. `pairs` is (headline, vader_label, model_label-or-None).

    Kept separate from the model call so this is testable without Ollama, and
    so a rerun against a different rubric compares on the same arithmetic.
    """
    compared = 0
    agreed = 0
    unscored = 0
    confusion: Counter[tuple[str, str]] = Counter()
    examples: list[Disagreement] = []

    for headline, vader_label, model_label in pairs:
        if vader_label not in TONE_LABELS:
            continue
        if model_label not in TONE_LABELS:
            unscored += 1
            continue
        compared += 1
        confusion[(vader_label, model_label)] += 1
        if vader_label == model_label:
            agreed += 1
        elif len(examples) < max_examples:
            examples.append(Disagreement(headline=headline, vader=vader_label, model=model_label))

    return AgreementReport(
        compared=compared,
        agreed=agreed,
        unscored=unscored,
        confusion=dict(confusion),
        disagreements=tuple(examples),
    )
