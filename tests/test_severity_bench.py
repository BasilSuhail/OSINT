"""Benching candidate graders against the human sheet (#646).

The bench decides whether the 4b grader can be replaced, so the tests that
matter are the ones about the gate refusing: a fast model that misses a death,
or one that agrees less often than what #593 published, must not read as a pass.
"""

from __future__ import annotations

import pytest

from app.severity import bench

HEADER = (
    "| headline | model severity | model band | model rationale "
    "| human severity | human band | rationale ok |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _sheet(*rows: str) -> str:
    return HEADER + "".join(rows)


def _row(headline, m_sev, m_band, m_reason, h_sev="", h_band="", ok=""):
    return f"| {headline} | {m_sev} | {m_band} | {m_reason} | {h_sev} | {h_band} | {ok} |\n"


def _responder(mapping: dict[str, dict]):
    """A stand-in model: headline substring → the JSON it would return."""

    def generate_json(prompt: str, *, model: str, keep_alive: str | None = None) -> dict:
        for needle, payload in mapping.items():
            if needle in prompt:
                return payload
        raise AssertionError(f"no canned answer for prompt: {prompt[-80:]}")

    return generate_json


class TestHumanCases:
    def test_keeps_only_rows_the_human_banded(self):
        cases = bench.human_cases(
            _sheet(
                _row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"),
                _row("Council debates budget", 0.0, "routine", "nothing happened"),
            )
        )

        assert [case["headline"] for case in cases] == ["3 killed in raid"]
        assert cases[0]["human_band"] == "grave"

    def test_drops_the_incumbent_verdict(self):
        # The candidate is re-run live; carrying the sheet's model columns
        # would compare a new model against an old model's answer.
        cases = bench.human_cases(
            _sheet(_row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        assert "model_severity" not in cases[0]
        assert "model_band" not in cases[0]


class TestBenchModel:
    def test_scores_a_candidate_against_the_human(self):
        cases = bench.human_cases(
            _sheet(
                _row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"),
                _row("Council debates budget", 0.0, "routine", "nothing", 0.05, "routine", "ok"),
            )
        )

        result = bench.bench_model(
            cases,
            model="candidate",
            generate_json=_responder(
                {
                    "3 killed in raid": {"severity": 0.7, "rationale": "Three people were killed."},
                    "Council debates budget": {"severity": 0.05, "rationale": "No harm occurred."},
                }
            ),
        )

        assert result["band_agreement"] == 1.0
        assert result["floor_violations"] == 0
        assert result["passes_gate"] is True

    def test_never_reuses_the_humans_rationale_judgement(self):
        # The human said "ok" about the incumbent's sentence. A candidate writes
        # a different sentence and has earned no opinion of it.
        cases = bench.human_cases(
            _sheet(_row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        result = bench.bench_model(
            cases,
            model="candidate",
            generate_json=_responder(
                {"3 killed": {"severity": 0.7, "rationale": "Three people were killed."}}
            ),
        )

        assert result["rationale_ok_rate"] is None

    def test_counts_guard_rejections_and_excludes_them(self):
        cases = bench.human_cases(
            _sheet(
                _row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"),
                _row("Council debates budget", 0.0, "routine", "nothing", 0.05, "routine", "ok"),
            )
        )

        result = bench.bench_model(
            cases,
            model="candidate",
            generate_json=_responder(
                {
                    # Invented figure — the numeral guard throws this away, and a
                    # thrown-away verdict never reaches stored data, so it must
                    # not be scored either.
                    "3 killed in raid": {"severity": 0.7, "rationale": "47 people were killed."},
                    "Council debates budget": {"severity": 0.05, "rationale": "No harm occurred."},
                }
            ),
        )

        assert result["rejected"] == 1
        assert result["rejection_rate"] == 0.5
        assert result["n"] == 1

    def test_a_dead_model_fails_rather_than_killing_the_run(self):
        cases = bench.human_cases(
            _sheet(_row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        def explode(prompt: str, *, model: str, keep_alive: str | None = None) -> dict:
            raise RuntimeError("model not found")

        result = bench.bench_model(cases, model="missing", generate_json=explode)

        assert result["errors"] == 1
        assert result["passes_gate"] is False

    def test_measures_time_per_headline(self):
        cases = bench.human_cases(
            _sheet(_row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        result = bench.bench_model(
            cases,
            model="candidate",
            generate_json=_responder(
                {"3 killed": {"severity": 0.7, "rationale": "Three people were killed."}}
            ),
        )

        assert result["seconds_per_headline"] is not None
        assert result["seconds_per_headline"] >= 0


class TestGate:
    def test_a_missed_death_fails_however_fast_it_is(self):
        cases = bench.human_cases(
            _sheet(_row("3 killed in raid", 0.6, "grave", "three killed", 0.65, "grave", "ok"))
        )

        result = bench.bench_model(
            cases,
            model="fast-and-wrong",
            generate_json=_responder(
                # Scored below the lethal floor on a headline the human banded
                # grave: the one failure the scale exists to prevent.
                {"3 killed": {"severity": 0.3, "rationale": "Some people were killed."}}
            ),
        )

        assert result["floor_violations"] == 1
        assert result["passes_gate"] is False

    @pytest.mark.parametrize(
        ("band_agreement", "expected"),
        [
            (bench.BAND_AGREEMENT_GATE, True),
            (bench.BAND_AGREEMENT_GATE - 0.001, False),
            (0.99, True),
        ],
    )
    def test_agreement_must_be_at_least_what_is_published(self, band_agreement, expected):
        result = {
            "band_agreement": band_agreement,
            "floor_violations": 0,
            "errors": 0,
        }

        assert bench.passes_gate(result) is expected

    def test_no_agreement_at_all_is_not_a_pass(self):
        result = {"band_agreement": None, "floor_violations": 0, "errors": 0}

        assert bench.passes_gate(result) is False


class TestRender:
    def _result(self, model, **overrides):
        base = {
            "model": model,
            "attempted": 50,
            "rejected": 0,
            "errors": 0,
            "rejection_rate": 0.0,
            "seconds_per_headline": 1.9,
            "n": 50,
            "n_banded": 50,
            "band_agreement": 0.9,
            "floor_violations": 0,
            "rationale_ok_rate": None,
            "mean_absolute_error": 0.1,
        }
        base.update(overrides)
        base["passes_gate"] = bench.passes_gate(base)
        return base

    def test_names_the_fastest_passing_candidate(self):
        report = bench.render(
            [
                self._result("incumbent", seconds_per_headline=1.9),
                self._result("small", seconds_per_headline=0.5),
            ],
            incumbent="incumbent",
        )

        assert "`small`" in report
        assert "Fastest candidate clearing the gate" in report

    def test_says_plainly_when_nothing_passes(self):
        report = bench.render(
            [
                self._result("incumbent", seconds_per_headline=1.9),
                self._result("small", seconds_per_headline=0.5, floor_violations=2),
            ],
            incumbent="incumbent",
        )

        assert "No candidate cleared the gate" in report
        assert "cascade" in report
