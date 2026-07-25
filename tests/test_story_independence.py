"""Independence must be recorded, not assumed from a missing record (#641).

`corroboration-v1.0` is exponential in `owner_count`, so these are the tests
that stop ten anonymous blogs reading as near-certainty once #442 admits them.
"""

from __future__ import annotations

from app.corroboration.score import corroboration_score
from app.stories.independence import independent_owners, owner_count, recorded_owner

OWNERS = {"reuters-feed": "reuters", "yahoo-feed": "reuters", "bbc-feed": "bbc"}


class TestRecordedOwner:
    def test_reads_a_recorded_owner(self) -> None:
        assert recorded_owner("bbc-feed", OWNERS) == "bbc"

    def test_an_unrecorded_source_has_no_owner(self) -> None:
        # Not the slug. Returning the slug is what let a source assert its own
        # independence.
        assert recorded_owner("some-blog", OWNERS) is None

    def test_a_blank_record_is_not_a_record(self) -> None:
        assert recorded_owner("x", {"x": "   "}) is None


class TestIndependentOwners:
    def test_syndication_collapses_to_one_owner(self) -> None:
        # The #355 case: Yahoo republishes Reuters wire, so they are one teller.
        assert independent_owners(["reuters-feed", "yahoo-feed"], OWNERS) == {"reuters"}

    def test_distinct_owners_stay_distinct(self) -> None:
        assert independent_owners(["reuters-feed", "bbc-feed"], OWNERS) == {"reuters", "bbc"}

    def test_unrecorded_sources_are_dropped_not_counted(self) -> None:
        assert independent_owners(["blog-a", "blog-b", "blog-c"], OWNERS) == set()

    def test_unrecorded_sources_do_not_dilute_recorded_ones(self) -> None:
        assert independent_owners(["bbc-feed", "blog-a"], OWNERS) == {"bbc"}


class TestOwnerCount:
    def test_counts_recorded_owners(self) -> None:
        assert owner_count(["reuters-feed", "bbc-feed"], OWNERS) == 2

    def test_ten_blogs_count_as_zero(self) -> None:
        assert owner_count([f"blog-{i}" for i in range(10)], OWNERS) == 0

    def test_an_empty_map_yields_zero_not_one_per_source(self) -> None:
        assert owner_count(["a", "b", "c"], {}) == 0


class TestAgainstTheCorroborationFormula:
    """The numbers this rule exists to prevent, asserted end to end."""

    def test_ten_unrecorded_blogs_score_zero_not_near_certainty(self) -> None:
        # Under the old slug fallback this was owner_count=10, doubt=2^-9,
        # score 0.998 — ten anonymous blogs outranking two wire services.
        count = owner_count([f"blog-{i}" for i in range(10)], OWNERS)
        score, components = corroboration_score(owner_count=count, confirmed=0, unconfirmed=0)
        assert score == 0.0
        assert components["owner_count"] == 0

    def test_two_wires_still_score_a_half(self) -> None:
        count = owner_count(["reuters-feed", "bbc-feed"], OWNERS)
        score, _ = corroboration_score(owner_count=count, confirmed=0, unconfirmed=0)
        assert score == 0.5

    def test_blogs_alongside_wires_change_nothing(self) -> None:
        # Perspective without confidence: #442 wants the blogs ingested and
        # shown, it does not want them voting on how sure we are.
        wires = owner_count(["reuters-feed", "bbc-feed"], OWNERS)
        with_blogs = owner_count(["reuters-feed", "bbc-feed", "blog-a", "blog-b", "blog-c"], OWNERS)
        assert wires == with_blogs

    def test_recording_an_owner_is_what_promotes_a_source(self) -> None:
        promoted = {**OWNERS, "blog-a": "some-collective"}
        assert owner_count(["reuters-feed", "bbc-feed", "blog-a"], promoted) == 3
        score, _ = corroboration_score(owner_count=3, confirmed=0, unconfirmed=0)
        assert score == 0.75
