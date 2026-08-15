"""Freezing a snapshot small enough and honest enough to publish (#demo).

The page these files feed is served from a static host to strangers. Two
things matter and both are tested here: what is kept, and whether the file
says what was left out.
"""

from __future__ import annotations

from typing import ClassVar

from scripts.demo_snapshot import (
    MARK_BUDGET,
    PAYLOAD_FIELDS,
    pick,
    positioned,
    thin,
    trim_event,
)


class TestTrimming:
    ROW: ClassVar[dict] = {
        "id": 1,
        "source": "usgs-quake",
        "category": "hazard",
        "occurred_at": "2026-08-15T00:00:00Z",
        "lat": 10.0,
        "lon": 20.0,
        "severity": 0.5,
        "country": "CL",
        "relation_count": 3,
        "fetched_at": "2026-08-15T00:01:00Z",
        "payload": {"magnitude": 6.1, "title": "M 6.1", "raw_feed_blob": "x" * 5000},
    }

    def test_keeps_what_a_map_draws(self):
        out = trim_event(self.ROW)
        assert out["id"] == 1
        assert out["lat"] == 10.0
        assert out["payload"]["magnitude"] == 6.1

    #: A payload is whatever a fetcher put there. An allow-list cannot publish
    #: a field nobody reviewed; an exclusion list can, the first time a fetcher
    #: adds one.
    def test_drops_everything_it_was_not_asked_for(self):
        out = trim_event(self.ROW)
        assert "raw_feed_blob" not in out["payload"]
        assert "relation_count" not in out
        assert set(out["payload"]) <= set(PAYLOAD_FIELDS)

    def test_a_row_with_no_payload_is_still_a_row(self):
        out = trim_event({"id": 2, "lat": 1.0, "lon": 2.0})
        assert out == {"id": 2, "lat": 1.0, "lon": 2.0}

    def test_pick_skips_fields_that_are_not_there(self):
        assert pick({"a": 1}, ("a", "b")) == {"a": 1}

    def test_a_row_with_no_position_cannot_be_drawn(self):
        rows = [{"lat": 1.0, "lon": 2.0}, {"lat": None, "lon": 2.0}, {"lon": 2.0}]
        assert len(positioned(rows)) == 1


class TestThinning:
    def test_leaves_a_small_list_alone(self):
        rows = [{"source": "gdacs"} for _ in range(10)]
        assert thin(rows, 700) == rows

    #: A wildfire feed reports thousands of hot pixels a day and one earthquake
    #: is one earthquake. Sampling both at one rate drops the quake to keep a
    #: hot pixel.
    def test_thins_the_crowded_feed_and_keeps_the_rest_whole(self):
        sparse = [{"source": "usgs-quake", "id": i} for i in range(50)]
        crowded = [{"source": "nasa-firms", "id": i} for i in range(5000)]
        kept = thin(sparse + crowded, 700)
        assert len(kept) <= 700
        assert sum(1 for r in kept if r["source"] == "usgs-quake") == 50

    #: Evenly, not the first N: a list sorted by time truncated at the front is
    #: one hour of one continent presented as a day's weather.
    def test_samples_across_the_list_rather_than_truncating(self):
        crowded = [{"source": "nasa-firms", "id": i} for i in range(1000)]
        kept = thin(crowded, 100)
        ids = [r["id"] for r in kept]
        assert max(ids) > 500
        assert len(ids) <= 100

    #: The budget exists because every mark is a DOM element and the first
    #: snapshot taken here held 2,756 of them.
    def test_the_budget_is_the_one_the_page_can_carry(self):
        assert 100 <= MARK_BUDGET <= 1500
