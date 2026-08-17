"""`make fetch` — priming an empty install (#993, #995).

The first version of this lived in `scripts/`, which the image does not copy, so
the command failed with `ModuleNotFoundError` on every invocation. `make -n`
printed the right line, because printing a command does not check that the module
it names exists. These tests check the two things that mattered and were not
checked: that it is importable from where the container runs it, and that the
Makefile calls the path it actually has.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.ingest.fetch_now import _describe, main

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
MAKEFILE = (ROOT / "Makefile").read_text()


class TestItRunsWhereItIsCalled:
    #: The bug: `scripts/` is not in the image, deliberately — most of it is
    #: host-side tooling that runs before any container exists.
    def test_lives_under_a_directory_the_image_copies(self) -> None:
        copied = re.findall(r"^COPY\s+(?:--\S+\s+)*(\S+)\s+\./?\S*$", DOCKERFILE, re.M)
        assert any(part == "app" or part.endswith("/app") for part in copied), copied

    def test_the_makefile_calls_the_module_that_exists(self) -> None:
        target = next(line for line in MAKEFILE.splitlines() if "fetch_now" in line)
        assert "app.ingest.fetch_now" in target
        assert "scripts.fetch_now" not in MAKEFILE

    #: Belt and braces: the import at the top of this file would already fail,
    #: but naming it makes the failure say what is wrong.
    def test_the_module_imports_by_its_container_path(self) -> None:
        import importlib

        assert importlib.import_module("app.ingest.fetch_now") is not None


class TestReporting:
    def test_names_an_unknown_source_and_refuses(self, capsys) -> None:
        assert main(["not-a-source"]) == 2
        assert "not-a-source" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            ({"state": "new_data", "fetched": 45, "inserted": 45}, "new_data (fetched 45, new 45)"),
            ({"state": "unchanged", "fetched": 40, "inserted": 0}, "unchanged (fetched 40, new 0)"),
            #: A fetcher that reports no counts must not render "None".
            ({"state": "skipped"}, "skipped"),
        ],
    )
    def test_describes_what_a_fetch_did(self, outcome: dict, expected: str) -> None:
        assert _describe(outcome) == expected


class TestOutputIsReadable:
    """Four faults from the first real run of `make fetch` (#997).

    All cosmetic, none behavioural — but the output is the whole product of this
    command, and a report nobody can read is not a report.
    """

    #: `rss-responsible-statecraft` is 26 characters and the column was 22, so
    #: the state ran straight into the name: `rss-responsible-statecraftnew_data`.
    def test_the_column_fits_the_longest_name_being_run(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("app.ingest.fetch_now.run_fetcher", lambda name: {"state": "empty"})
        monkeypatch.setattr(
            "app.ingest.fetch_now.registered_names",
            lambda: {"a", "rss-responsible-statecraft"},
        )
        assert main(["a", "rss-responsible-statecraft"]) == 0
        out = capsys.readouterr().out
        assert "rss-responsible-statecraft  empty" in out
        assert "statecraftempty" not in out

    #: `run_fetcher` catches SourceMisconfiguredError itself and reports it as a
    #: state, so the exception never arrived and the dormant summary never
    #: printed — a source with no key was indistinguishable from a broken one.
    def test_a_state_of_misconfigured_counts_as_dormant(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.ingest.fetch_now.run_fetcher", lambda name: {"state": "misconfigured"}
        )
        monkeypatch.setattr("app.ingest.fetch_now.registered_names", lambda: {"fred"})
        assert main(["fred"]) == 0
        out = capsys.readouterr().out
        assert "1 dormant" in out
        assert "fred" in out

    def test_a_state_of_failed_is_counted_and_explained(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr("app.ingest.fetch_now.run_fetcher", lambda name: {"state": "failed"})
        monkeypatch.setattr("app.ingest.fetch_now.registered_names", lambda: {"rss-x"})
        assert main(["rss-x"]) == 0
        out = capsys.readouterr().out
        assert "1 failed" in out
        #: A 403 is a timed quarantine and a retry, not something to go and fix.
        assert "quarantined" in out

    #: A fetcher logging to the same stream mid-call used to land inside a
    #: half-written line. One feed emitted 25 warnings and destroyed the layout.
    def test_a_source_line_is_written_whole_after_the_call(self, capsys, monkeypatch) -> None:
        def noisy(name: str) -> dict:
            print("a warning from the fetcher")
            return {"state": "new_data", "fetched": 3, "inserted": 3}

        monkeypatch.setattr("app.ingest.fetch_now.run_fetcher", noisy)
        monkeypatch.setattr("app.ingest.fetch_now.registered_names", lambda: {"gdelt"})
        assert main(["gdelt"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert "a warning from the fetcher" in lines
        summary = next(line for line in lines if "gdelt" in line)
        assert summary.strip() == "gdelt  new_data (fetched 3, new 3)"
