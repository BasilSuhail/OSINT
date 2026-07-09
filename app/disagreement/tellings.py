"""Per-country tellings — one divergence number per story (WS-B step 2, #370).

Declared mechanics under METHOD_VERSION, no tuning:

    divergence(story) = mean over unordered country-group pairs of
                        (1 - cosine(centroid_g, centroid_h))

Groups are outlet *origin* countries (``outlet_country_map``, #368) with at
least one titled member; a member whose source has no known origin is left
out rather than guessed. Fewer than two groups → ``None``: a single-country
story has no cross-country telling to diverge.

The centroids are TF-IDF vectors over the story's own member titles — the
same vectorizer the clusterer uses — so the number reads as "how differently
do the country blocs word this one story". This is the Ground News
left/center/right spread generalised to countries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations
from typing import Any

from app.stories.vectorize import build_idf, cosine, tokenize, vectorize

METHOD_VERSION: str = "disagreement-v1.0"


def story_divergence(
    members: Iterable[Mapping[str, Any]],
    *,
    country_map: Mapping[str, str],
) -> dict[str, Any] | None:
    """Divergence + components for one story, or None when < 2 country groups.

    `members`: story member articles — title, source.
    """
    grouped: dict[str, list[list[str]]] = {}
    all_tokens: list[list[str]] = []
    for member in members:
        country = country_map.get(member["source"])
        tokens = tokenize(member.get("title") or "")
        if country is None or not tokens:
            continue
        grouped.setdefault(country, []).append(tokens)
        all_tokens.append(tokens)

    if len(grouped) < 2:
        return None

    idf = build_idf(all_tokens)
    centroids: dict[str, dict[str, float]] = {}
    for country, docs in grouped.items():
        centroid: dict[str, float] = {}
        for tokens in docs:
            for token, weight in vectorize(tokens, idf).items():
                centroid[token] = centroid.get(token, 0.0) + weight / len(docs)
        centroids[country] = centroid

    # Identical centroids can give cosine 1 + ε in floats; clamp each pair to [0, 1].
    pair_distances = {
        f"{g}|{h}": min(1.0, max(0.0, 1.0 - cosine(centroids[g], centroids[h])))
        for g, h in combinations(sorted(centroids), 2)
    }
    divergence = sum(pair_distances.values()) / len(pair_distances)

    return {
        "divergence": divergence,
        "components": {
            "groups": {country: len(docs) for country, docs in sorted(grouped.items())},
            "n_pairs": len(pair_distances),
            # Per-pair evidence — what the (country-pair, month) roll-up (#372) feeds on.
            "pairs": pair_distances,
            "method_version": METHOD_VERSION,
        },
    }
