"""WS-C step 1 — story-cluster threshold audit (issue #334).

Produces a reviewable audit sheet for the 0.35 similarity threshold before
any corroboration logic builds on the clusters. Two failure modes matter:

- **over-merge**: unrelated stories glued into one cluster (threshold too low
  for the corpus) — visible by reading a sampled cluster's member titles;
- **under-merge**: one real-world story fragmented across clusters (threshold
  too high) — surfaced as *near-miss pairs*: cluster centroids whose cosine
  sits just below the joining threshold.

Pure functions here; `python -m app.stories.audit` (make stories-audit) does
the DB reads and writes `data/exports/stories-audit.md` for hand-checking.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.stories.cluster import SIMILARITY_THRESHOLD
from app.stories.vectorize import build_idf, cosine, tokenize, vectorize

#: Near-miss band: pairs at or above the threshold would have been joined,
#: pairs far below are genuinely different stories. The band just under the
#: threshold is where split errors live.
NEAR_MISS_LOW: float = 0.20

#: Default stratum sizes — ~30 clusters total before dedup overlap.
TOP_BY_MEMBERS = 10
TOP_BY_OUTLETS = 5
RANDOM_MULTI = 10
RANDOM_SINGLETON = 5


def stratify_sample(
    clusters: Iterable[Mapping[str, Any]],
    *,
    seed: int,
    top_by_members: int = TOP_BY_MEMBERS,
    top_by_outlets: int = TOP_BY_OUTLETS,
    random_multi: int = RANDOM_MULTI,
    random_singleton: int = RANDOM_SINGLETON,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Stratified, deterministic sample of clusters to hand-check.

    Strata (priority order, a cluster appears once under its first match):
    largest by member_count (over-merge suspects), loudest by outlet_count,
    random multi-member, random singletons. Input items need at least:
    story_id, title, member_count, outlet_count.
    """
    rows = list(clusters)
    rng = random.Random(seed)
    picked: dict[int, str] = {}

    def take(candidates: list[Mapping[str, Any]], stratum: str, n: int) -> None:
        for row in candidates:
            if n <= 0:
                return
            if row["story_id"] in picked:
                continue
            picked[row["story_id"]] = stratum
            n -= 1

    by_members = sorted(rows, key=lambda r: (-r["member_count"], r["story_id"]))
    take(by_members, "largest", top_by_members)

    by_outlets = sorted(rows, key=lambda r: (-r["outlet_count"], r["story_id"]))
    take(by_outlets, "loudest", top_by_outlets)

    multi = [r for r in rows if r["member_count"] >= 2]
    rng.shuffle(multi)
    take(multi, "random-multi", random_multi)

    singles = [r for r in rows if r["member_count"] == 1]
    rng.shuffle(singles)
    take(singles, "random-singleton", random_singleton)

    order = {row["story_id"]: i for i, row in enumerate(rows)}
    return sorted(
        ((stratum, row) for row in rows if (stratum := picked.get(row["story_id"])) is not None),
        key=lambda item: order[item[1]["story_id"]],
    )


def cluster_centroids(
    titles_by_story: Mapping[int, list[str]],
) -> dict[int, dict[str, float]]:
    """Mean tf-idf vector per cluster, idf built over all member titles."""
    tokenized = {
        story_id: [tokenize(title) for title in titles]
        for story_id, titles in titles_by_story.items()
    }
    idf = build_idf(tokens for doc_lists in tokenized.values() for tokens in doc_lists)
    centroids: dict[int, dict[str, float]] = {}
    for story_id, doc_lists in tokenized.items():
        vectors = [vectorize(tokens, idf) for tokens in doc_lists if tokens]
        if not vectors:
            continue
        centroid: dict[str, float] = defaultdict(float)
        for vector in vectors:
            for token, weight in vector.items():
                centroid[token] += weight / len(vectors)
        centroids[story_id] = dict(centroid)
    return centroids


def near_miss_pairs(
    centroids: Mapping[int, dict[str, float]],
    *,
    low: float = NEAR_MISS_LOW,
    high: float = SIMILARITY_THRESHOLD,
    limit: int = 10,
) -> list[tuple[int, int, float]]:
    """Cluster pairs whose centroid cosine lands in [low, high) — split suspects.

    Candidate pairs come from a shared-token inverted index, so the pairwise
    work stays proportional to real overlap instead of n^2.
    """
    index: dict[str, list[int]] = defaultdict(list)
    for story_id, centroid in centroids.items():
        for token in centroid:
            index[token].append(story_id)

    candidates: set[tuple[int, int]] = set()
    for story_ids in index.values():
        if len(story_ids) < 2:
            continue
        ordered = sorted(story_ids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                candidates.add((a, b))

    scored = []
    for a, b in candidates:
        similarity = cosine(centroids[a], centroids[b])
        if low <= similarity < high:
            scored.append((a, b, similarity))
    scored.sort(key=lambda item: -item[2])
    return scored[:limit]


def render_audit_markdown(
    sampled: list[tuple[str, Mapping[str, Any]]],
    members_by_story: Mapping[int, list[Mapping[str, Any]]],
    pairs: list[tuple[int, int, float]],
    titles_by_story: Mapping[int, str],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
) -> str:
    """The hand-check sheet: every sampled cluster with members, blank verdicts."""
    lines = [
        "# Story-cluster threshold audit (WS-C step 1, issue #334)",
        "",
        f"Joining threshold under audit: **{threshold}** (stories-v1.0).",
        "Verdict per cluster: `coherent` / `over-merged` / `mixed` — fill the last column.",
        "",
    ]
    for stratum, row in sampled:
        story_id = row["story_id"]
        lines += [
            f"## story {story_id} — [{stratum}] {row['member_count']} members, "
            f"{row['outlet_count']} outlets",
            "",
            "| similarity | outlet | member title | ",
            "|---|---|---|",
        ]
        for member in members_by_story.get(story_id, []):
            lines.append(f"| {member['similarity']:.2f} | {member['source']} | {member['title']} |")
        lines += ["", "**Verdict**: _______", ""]

    lines += [
        "---",
        "",
        f"## Near-miss pairs (centroid cosine in [{NEAR_MISS_LOW}, {threshold})) — split suspects",
        "",
        "| cosine | story A | story B |",
        "|---|---|---|",
    ]
    for a, b, similarity in pairs:
        lines.append(
            f"| {similarity:.2f} | {a}: {titles_by_story.get(a, '')} "
            f"| {b}: {titles_by_story.get(b, '')} |"
        )
    lines += ["", "**Same real-world story?** Mark any pair that should have merged.", ""]
    return "\n".join(lines)


def main() -> int:  # pragma: no cover - thin DB/IO shell over the pure layer
    import os
    from pathlib import Path

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import get_engine
    from app.db_models import EventRow, StoryMemberRow, StoryRow

    with Session(get_engine()) as session:
        stories = [
            {
                "story_id": row.id,
                "title": row.title,
                "member_count": row.member_count,
                "outlet_count": row.outlet_count,
            }
            for row in session.execute(select(StoryRow)).scalars()
        ]
        member_rows = session.execute(
            select(
                StoryMemberRow.story_id,
                StoryMemberRow.similarity,
                EventRow.source,
                EventRow.payload,
            ).join(EventRow, EventRow.id == StoryMemberRow.event_id)
        ).all()

    members_by_story: dict[int, list[dict[str, Any]]] = defaultdict(list)
    titles_by_story_members: dict[int, list[str]] = defaultdict(list)
    for story_id, similarity, source, payload in member_rows:
        title = (payload or {}).get("title") or ""
        members_by_story[story_id].append(
            {"similarity": similarity, "source": source, "title": title}
        )
        titles_by_story_members[story_id].append(title)

    # Event retention prunes old news rows, which silently empties the member
    # join for old clusters. The threshold governs joins inside the rolling
    # window, so the audit targets clusters whose evidence still resolves.
    total = len(stories)
    stories = [row for row in stories if members_by_story.get(row["story_id"])]
    print(f"{len(stories)}/{total} clusters have resolvable members (rest retention-pruned)")

    sampled = stratify_sample(stories, seed=334)  # seed = the audit issue number
    centroids = cluster_centroids(titles_by_story_members)
    pairs = near_miss_pairs(centroids)

    report = render_audit_markdown(
        sampled,
        members_by_story,
        pairs,
        {row["story_id"]: row["title"] for row in stories},
    )
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    out = exports / "stories-audit.md"
    out.write_text(report)
    print(f"audit sheet: {len(sampled)} clusters sampled, {len(pairs)} near-miss pairs → {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
