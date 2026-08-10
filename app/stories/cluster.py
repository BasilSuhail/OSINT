"""Cluster layer — greedy leader clustering of unassigned articles.

Pure functions. Existing assignments are never revisited: an article joins
the best-matching story (existing or newly founded this run) when its cosine
against the story centroid clears the threshold, else founds a new story.
Deterministic in (occurred_at, event_id) order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.stories.independence import independent_owners
from app.stories.vectorize import build_idf, cosine, tokenize, vectorize

METHOD_VERSION: str = "stories-v1.0"

#: Join threshold — see the design doc's worked examples: paraphrases ~0.6+,
#: same-story new-angle headlines ~0.4, unrelated ~0.0-0.1.
SIMILARITY_THRESHOLD: float = 0.35

#: Distinct content tokens a headline must carry to take part in clustering at
#: all (#890). Below this it says nothing about the world: "Morning update" is
#: the name of a daily column, and with `update` already boilerplate it reduces
#: to the single word `morning`. A one-token vector points in one direction, so
#: it scores high against every article that happens to use that word — an
#: outlet's newsletter collected a foreign market wrap into a six-day "story"
#: told by two independent owners, which is a corroboration claim about two
#: pieces that shared nothing but the hour they were published at.
MIN_CONTENT_TOKENS: int = 2

#: Tokens an article must share with a story before similarity is allowed to
#: speak (#890). Cosine cannot tell a paraphrase from a coincidence on the
#: strength of one word: real retellings of the same event overlap on several.
#: Measured against the live corpus, this refuses 1.1% of existing joins, and
#: the refused ones read as "who", "here", "tomorrow", "latest".
MIN_SHARED_TOKENS: int = 2


def _is_substantial(tokens: list[str]) -> bool:
    """Whether a tokenized headline says enough to be clustered at all (#890)."""
    return len(set(tokens)) >= MIN_CONTENT_TOKENS


@dataclass
class ClusterResult:
    """New stories founded this run + new memberships (existing or new stories)."""

    new_stories: list[dict[str, Any]] = field(default_factory=list)
    new_members: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Story:
    story_id: int | None  # None → founded this run; index into new_stories
    new_index: int | None
    centroid: dict[str, float]
    n: int

    def add(self, vector: dict[str, float]) -> None:
        merged = {token: weight * self.n for token, weight in self.centroid.items()}
        for token, weight in vector.items():
            merged[token] = merged.get(token, 0.0) + weight
        self.n += 1
        self.centroid = {token: weight / self.n for token, weight in merged.items()}


def cluster_articles(
    articles: Iterable[Mapping[str, Any]],
    *,
    existing: Iterable[Mapping[str, Any]],
    owner_map: Mapping[str, str] | None = None,
) -> ClusterResult:
    """Assign unassigned articles to stories.

    A headline carrying fewer than `MIN_CONTENT_TOKENS` content words takes no
    part: it neither founds a story nor joins one, and it is left out of the
    centroid rebuild (#890). A join also needs `MIN_SHARED_TOKENS` words in
    common with the story before its similarity counts.

    `articles`: unassigned news events — event_id, title, source, occurred_at.
    `existing`: current members in the window — event_id, story_id, title.
    `owner_map`: source slug → content owner (#355). A slug with no recorded
    owner contributes nothing to `owner_count` (#641) — independence is
    positively established, never inferred from a missing record. An empty map
    therefore yields `owner_count = 0`, not one owner per source.
    """
    owner_map = owner_map or {}
    articles = sorted(articles, key=lambda a: (a["occurred_at"], a["event_id"]))
    existing = list(existing)

    tokenized_articles = [(a, tokenize(a.get("title") or "")) for a in articles]
    tokenized_articles = [(a, t) for a, t in tokenized_articles if _is_substantial(t)]
    if not tokenized_articles:
        return ClusterResult()

    corpus = [t for _, t in tokenized_articles] + [tokenize(m["title"] or "") for m in existing]
    idf = build_idf(corpus)

    # Rebuild centroids of existing stories from their member titles.
    stories: dict[int | tuple[str, int], _Story] = {}
    for member in existing:
        tokens = tokenize(member["title"] or "")
        # A thin headline is left out of the rebuild as well as the intake.
        # Kept in, it holds the centroid on its single word and the story goes
        # on collecting tomorrow's edition of the same column (#890).
        if not _is_substantial(tokens):
            continue
        vector = vectorize(tokens, idf)
        story = stories.get(member["story_id"])
        if story is None:
            stories[member["story_id"]] = _Story(
                story_id=member["story_id"], new_index=None, centroid=vector, n=1
            )
        else:
            story.add(vector)

    result = ClusterResult()
    outlet_sets: list[set[str]] = []
    owner_sets: list[set[str]] = []

    for article, tokens in tokenized_articles:
        vector = vectorize(tokens, idf)
        best: _Story | None = None
        best_similarity = 0.0
        for story in stories.values():
            if len(vector.keys() & story.centroid.keys()) < MIN_SHARED_TOKENS:
                continue
            similarity = cosine(vector, story.centroid)
            if similarity >= SIMILARITY_THRESHOLD and similarity > best_similarity:
                best, best_similarity = story, similarity

        if best is None:
            new_index = len(result.new_stories)
            result.new_stories.append(
                {
                    "method_version": METHOD_VERSION,
                    "title": article["title"],
                    "first_title": article["title"],
                    "first_seen": article["occurred_at"],
                    "last_seen": article["occurred_at"],
                    "member_count": 1,
                    "outlet_count": 1,
                    "owner_count": len(independent_owners([article["source"]], owner_map)),
                }
            )
            outlet_sets.append({article["source"]})
            owner_sets.append(independent_owners([article["source"]], owner_map))
            story = _Story(story_id=None, new_index=new_index, centroid=vector, n=1)
            stories[("new", new_index)] = story
            result.new_members.append(
                {
                    "event_id": article["event_id"],
                    "story_id": None,
                    "story_index": new_index,
                    "similarity": 1.0,
                }
            )
        else:
            best.add(vector)
            if best.new_index is not None:
                story_row = result.new_stories[best.new_index]
                story_row["member_count"] += 1
                story_row["last_seen"] = article["occurred_at"]
                outlet_sets[best.new_index].add(article["source"])
                story_row["outlet_count"] = len(outlet_sets[best.new_index])
                owner_sets[best.new_index] |= independent_owners([article["source"]], owner_map)
                story_row["owner_count"] = len(owner_sets[best.new_index])
            result.new_members.append(
                {
                    "event_id": article["event_id"],
                    "story_id": best.story_id,
                    "story_index": best.new_index,
                    "similarity": best_similarity,
                }
            )

    return result
