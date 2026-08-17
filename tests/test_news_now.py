"""`make news` — the half of the console `make fetch` does not build (#997).

`make fetch` fills the map. The stories, the cards and the written summary are
downstream of it, and beat builds them on three separate schedules, so a fresh
install shows a full map beside "No stories in the window yet" for up to
three quarters of an hour.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.news_now import _STAGES, _bar, _describe, _gist, main

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text()


def _only_gist(monkeypatch) -> None:
    """Run the gist stage alone, so a test needs no database for the others."""
    monkeypatch.setattr(
        "app.news_now._STAGES", (("gist", "the summary line on each story card", None),)
    )


class TestTheOrder:
    #: The gist and the narrative both read clusters, and a story with no gist
    #: cannot be drawn as a card. Any other order half-builds the console.
    def test_clusters_are_built_before_anything_reads_them(self) -> None:
        assert [name for name, _, _ in _STAGES] == ["cluster", "gist", "narrate"]

    def test_every_stage_says_what_it_produces_on_screen(self) -> None:
        for _, produces, _ in _STAGES:
            assert produces and produces[0].islower()


class TestItRunsWhereItIsCalled:
    def test_the_makefile_calls_the_module_that_exists(self) -> None:
        target = next(line for line in MAKEFILE.splitlines() if "news_now" in line)
        assert "app.news_now" in target

    def test_it_lives_under_app_so_the_image_has_it(self) -> None:
        assert (ROOT / "app" / "news_now.py").exists()


class TestReporting:
    def test_refuses_an_argument_it_does_not_know(self, capsys) -> None:
        assert main(["gdelt"]) == 2
        assert "only --all" in capsys.readouterr().err

    #: The brain declines when the box has no headroom and says so in `reason`.
    #: That is the design working, not a failure.
    def test_a_declined_brain_stage_reads_as_skipped(self) -> None:
        assert _describe({"persisted": False, "reason": "busy box"}) == "skipped — busy box"

    def test_a_written_narrative_says_so(self) -> None:
        assert _describe({"persisted": True, "reason": "ok"}) == "written — ok"

    #: The tasks do not share a result shape, so empty counts are dropped rather
    #: than printed as zeros nobody needs to read.
    def test_counts_are_reported_and_empty_ones_dropped(self) -> None:
        assert _describe({"stories": 4, "assigned": 0}) == "stories=4"

    def test_nothing_to_do_is_said_rather_than_shown_blank(self) -> None:
        assert _describe({"stories": 0}) == "nothing to do"

    def test_a_failing_stage_does_not_stop_the_others(self, capsys, monkeypatch) -> None:
        calls: list[str] = []

        def boom() -> dict:
            calls.append("cluster")
            raise RuntimeError("no database")

        def fine() -> dict:
            calls.append("later")
            return {"persisted": True, "reason": "ok"}

        monkeypatch.setattr(
            "app.news_now._STAGES",
            (("cluster", "clusters", boom), ("narrate", "the summary", fine)),
        )
        assert main([]) == 0
        assert calls == ["cluster", "later"]
        out = capsys.readouterr().out
        assert "failed — RuntimeError: no database" in out
        assert "1 stage(s) failed: cluster" in out


class TestTheQuickRunSaysWhatItLeftUndone:
    """The gist stage is bounded at 20 per call (#997).

    On a first fill of 1,128 stories that is a rounding error, and the run
    reported `enriched=20` with nothing saying the other 1,108 were still
    waiting — which reads as finished.
    """

    def test_it_says_how_far_it_got_and_offers_the_long_way(self, capsys, monkeypatch) -> None:
        _only_gist(monkeypatch)
        monkeypatch.setattr(
            "app.news_now._enrich_batch",
            lambda size: {"window_stories": 1128, "enriched": size},
        )
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "20 of 1128 stories have a gist" in out
        assert "make news-all" in out

    #: A quick run stops at its target, not at the end of the window. The bar
    #: counts towards 20 so reaching the end of it means what it says.
    def test_the_quick_run_stops_at_its_target(self, capsys, monkeypatch) -> None:
        _only_gist(monkeypatch)
        sizes: list[int] = []

        def enrich(size: int) -> dict:
            sizes.append(size)
            return {"window_stories": 1128, "enriched": size}

        monkeypatch.setattr("app.news_now._enrich_batch", enrich)
        assert main([]) == 0
        assert sum(sizes) == 20
        assert "20/20 stories" in capsys.readouterr().out

    def test_a_finished_window_makes_no_such_offer(self, capsys, monkeypatch) -> None:
        _only_gist(monkeypatch)
        monkeypatch.setattr(
            "app.news_now._enrich_batch",
            lambda size: {"window_stories": 20, "enriched": size},
        )
        assert main([]) == 0
        assert "news-all" not in capsys.readouterr().out


class TestTheLongRun:
    def test_only_all_is_accepted_as_an_argument(self, capsys) -> None:
        assert main(["--everything"]) == 2
        assert "only --all" in capsys.readouterr().err

    def test_it_keeps_going_until_a_batch_finds_nothing(self) -> None:
        batches = [
            {"window_stories": 50, "enriched": 20},
            {"window_stories": 50, "enriched": 20},
            {"window_stories": 50, "enriched": 10},
            {"window_stories": 50, "enriched": 0},
        ]
        calls = iter(batches)
        outcome = _gist(target=None, step=20, enrich=lambda size: next(calls))
        assert outcome == {"window_stories": 50, "enriched": 50}

    #: A declined batch must stop rather than spin: the box has no headroom and
    #: calling again would loop forever reporting nothing.
    def test_a_declined_batch_stops_and_keeps_the_reason(self) -> None:
        outcome = _gist(
            target=None, step=20, enrich=lambda size: {"persisted": False, "reason": "busy box"}
        )
        assert outcome == {"persisted": False, "reason": "busy box"}

    def test_all_gists_everything_rather_than_one_batch(self, capsys, monkeypatch) -> None:
        calls = iter(
            [
                {"window_stories": 40, "enriched": 20},
                {"window_stories": 40, "enriched": 20},
                {"window_stories": 40, "enriched": 0},
            ]
        )
        monkeypatch.setattr("app.news_now._enrich_batch", lambda size: next(calls))
        monkeypatch.setattr(
            "app.news_now._STAGES", (("gist", "gists", lambda: {"never": "called"}),)
        )
        assert main(["--all"]) == 0
        out = capsys.readouterr().out
        assert "40/40 stories" in out
        assert "never" not in out


class TestTheProgressBar:
    def test_it_fills_as_it_goes(self) -> None:
        assert _bar(0, 100, 0.0).startswith("[........................]")
        assert "[############............]" in _bar(50, 100, 0.0)
        assert "[########################]" in _bar(100, 100, 0.0)

    def test_it_counts_stories_not_batches(self) -> None:
        assert "20/1128 stories" in _bar(20, 1128, 0.0)

    #: An estimate is the difference between waiting and wondering whether it
    #: has hung. Nothing to estimate from on the first line, so it says so.
    def test_it_estimates_only_once_it_has_something_to_estimate_from(self) -> None:
        assert "estimating" in _bar(0, 100, 0.0)

    #: Three tiers, because "nearly done" at 4 of 20 is a claim the reader can
    #: check against the counts on the same line and see is false.
    def test_minutes_seconds_and_nearly_done_are_distinguished(self) -> None:
        now = time.monotonic()
        assert "~3 min left" in _bar(4, 20, now - 40)
        assert "~10s left" in _bar(16, 20, now - 40)
        assert "nearly done" in _bar(1100, 1128, now - 20)

    def test_a_long_first_fill_is_estimated_in_minutes(self) -> None:
        assert "~185 min left" in _bar(20, 1128, time.monotonic() - 200)

    def test_a_zero_total_does_not_divide_by_zero(self) -> None:
        assert _bar(0, 0, 0.0)
