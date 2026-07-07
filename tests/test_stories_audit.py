"""Tests for `app.stories.audit` — WS-C step 1 threshold audit tooling."""

from __future__ import annotations

from app.stories.audit import (
    cluster_centroids,
    near_miss_pairs,
    render_audit_markdown,
    stratify_sample,
)
from app.stories.cluster import SIMILARITY_THRESHOLD


def _cluster(story_id: int, members: int, outlets: int, title: str = "t") -> dict:
    return {
        "story_id": story_id,
        "title": title,
        "member_count": members,
        "outlet_count": outlets,
    }


class TestStratifySample:
    def test_deterministic_for_same_seed(self) -> None:
        rows = [_cluster(i, members=1 + i % 5, outlets=1 + i % 3) for i in range(100)]
        first = stratify_sample(rows, seed=334)
        second = stratify_sample(rows, seed=334)
        assert first == second

    def test_each_cluster_sampled_once(self) -> None:
        # The biggest cluster is also the loudest — must not appear twice.
        rows = [_cluster(1, members=50, outlets=40)] + [
            _cluster(i, members=2, outlets=1) for i in range(2, 40)
        ]
        sampled = stratify_sample(rows, seed=1)
        ids = [row["story_id"] for _, row in sampled]
        assert len(ids) == len(set(ids))
        strata = {row["story_id"]: stratum for stratum, row in sampled}
        assert strata[1] == "largest"

    def test_strata_quotas_respected(self) -> None:
        rows = [_cluster(i, members=1 + (i % 7), outlets=1 + (i % 4)) for i in range(200)]
        sampled = stratify_sample(
            rows, seed=7, top_by_members=3, top_by_outlets=2, random_multi=4, random_singleton=2
        )
        counts: dict[str, int] = {}
        for stratum, _ in sampled:
            counts[stratum] = counts.get(stratum, 0) + 1
        assert counts["largest"] == 3
        assert counts["loudest"] == 2
        assert counts["random-multi"] == 4
        assert counts["random-singleton"] == 2

    def test_small_corpus_does_not_crash(self) -> None:
        rows = [_cluster(1, members=1, outlets=1)]
        sampled = stratify_sample(rows, seed=1)
        assert len(sampled) == 1


class TestNearMissPairs:
    def test_finds_pair_below_threshold_only(self) -> None:
        titles = {
            1: ["earthquake strikes coastal turkey overnight"],
            2: ["turkey coastal earthquake overnight rescue"],
            3: ["parliament passes budget vote"],
        }
        centroids = cluster_centroids(titles)
        pairs = near_miss_pairs(centroids, low=0.05, high=SIMILARITY_THRESHOLD, limit=10)
        pair_ids = {(a, b) for a, b, _ in pairs}
        assert all(low_sim < SIMILARITY_THRESHOLD for _, _, low_sim in pairs)
        assert (1, 3) not in pair_ids
        assert (2, 3) not in pair_ids

    def test_identical_clusters_excluded_as_above_threshold(self) -> None:
        titles = {
            1: ["volcano erupts on iceland peninsula"],
            2: ["volcano erupts on iceland peninsula"],
        }
        centroids = cluster_centroids(titles)
        assert near_miss_pairs(centroids, low=0.2, limit=10) == []

    def test_limit_and_ordering(self) -> None:
        titles = {i: [f"shared token{i} core words here"] for i in range(1, 8)}
        centroids = cluster_centroids(titles)
        pairs = near_miss_pairs(centroids, low=0.0, high=1.01, limit=3)
        assert len(pairs) == 3
        similarities = [s for _, _, s in pairs]
        assert similarities == sorted(similarities, reverse=True)


class TestRenderAuditMarkdown:
    def test_sheet_contains_members_and_verdict_slots(self) -> None:
        sampled = [("largest", _cluster(1, members=2, outlets=2, title="quake in turkey"))]
        members = {
            1: [
                {"similarity": 1.0, "source": "rss-bbc", "title": "quake in turkey"},
                {"similarity": 0.41, "source": "rss-reuters", "title": "turkey quake toll rises"},
            ]
        }
        pairs = [(1, 2, 0.31)]
        sheet = render_audit_markdown(sampled, members, pairs, {1: "quake in turkey", 2: "other"})
        assert "story 1 — [largest] 2 members, 2 outlets" in sheet
        assert "turkey quake toll rises" in sheet
        assert "rss-reuters" in sheet
        assert sheet.count("**Verdict**: _______") == 1
        assert "0.31" in sheet
        assert str(SIMILARITY_THRESHOLD) in sheet
