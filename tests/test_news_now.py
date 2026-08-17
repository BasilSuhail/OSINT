"""`make news` — the half of the console `make fetch` does not build (#997).

`make fetch` fills the map. The stories, the cards and the written summary are
downstream of it, and beat builds them on three separate schedules, so a fresh
install shows a full map beside "No stories in the window yet" for up to
three quarters of an hour.
"""

from __future__ import annotations

from pathlib import Path

from app.news_now import _STAGES, _describe, main

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text()


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
    def test_takes_no_arguments(self, capsys) -> None:
        assert main(["gdelt"]) == 2
        assert "no arguments" in capsys.readouterr().err

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
