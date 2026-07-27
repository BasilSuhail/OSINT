"""Grading by band name instead of by number (#649).

#646 found small models classifying correctly in prose and then emitting an
unrelated float — "a routine policy or business matter", scored 0.6. This
protocol asks only for the label and does the mapping in code, so the tests that
matter are: the label maps to something inside its band, an unknown label is
refused rather than guessed at, and the guards did not get weaker on the way.
"""

from __future__ import annotations

import pytest

from app.severity import bench, news, scale


class TestBandLookup:
    @pytest.mark.parametrize("name", [band.name for band in scale.BANDS])
    def test_every_band_is_findable_by_its_own_name(self, name):
        assert scale.band_by_name(name) is not None

    def test_case_and_whitespace_do_not_decide_a_verdict(self):
        assert scale.band_by_name("  GRAVE ") is scale.band_by_name("grave")

    @pytest.mark.parametrize("name", ["severe", "", "0.6", "very bad", "grave-ish"])
    def test_an_unknown_label_is_refused_not_guessed(self, name):
        # Coercing "severe" to the nearest band would invent a judgement the
        # model never made.
        assert scale.band_by_name(name) is None

    @pytest.mark.parametrize("band", scale.BANDS)
    def test_a_bands_value_lands_inside_that_band(self, band):
        value = scale.value_for_band(band)

        assert band.lower < value < band.upper
        assert scale.band_for(value).name == band.name

    def test_grave_maps_clear_of_the_lethal_floor(self):
        # Not onto it: the CII unrest test is `>= 0.6`, and putting every
        # confirmed death exactly on the boundary makes that a float knife-edge.
        value = scale.value_for_band(scale.band_by_name("grave"))

        assert value > scale.LETHAL_FLOOR


class TestBandPrompt:
    def test_asks_for_a_label_and_never_for_a_number(self):
        prompt = news.build_band_prompt("3 killed in a bombing")

        assert '"band"' in prompt
        assert '"severity"' not in prompt

    def test_states_every_band_the_parser_accepts(self):
        prompt = news.build_band_prompt("3 killed in a bombing")

        for band in scale.BANDS:
            assert band.name in prompt

    def test_keeps_the_lethal_floor_as_a_band_instruction(self):
        prompt = news.build_band_prompt("3 killed in a bombing")

        assert "AT LEAST grave" in prompt


class TestBandVerdict:
    def test_a_named_band_becomes_a_value_in_that_band(self):
        verdict = news.band_verdict_from_payload(
            {"band": "grave", "rationale": "Three people were killed."},
            headline="Three killed in a bombing",
        )

        assert verdict is not None
        assert verdict.band == "grave"
        assert verdict.value >= scale.LETHAL_FLOOR
        assert verdict.method == news.BAND_METHOD

    def test_an_unknown_band_is_rejected(self):
        verdict = news.band_verdict_from_payload(
            {"band": "severe", "rationale": "Three people were killed."},
            headline="Three killed in a bombing",
        )

        assert verdict is None

    def test_a_missing_rationale_is_rejected(self):
        # Same rule as the numeric path: an unexplained grade is the thing the
        # scale module exists to stop.
        verdict = news.band_verdict_from_payload(
            {"band": "grave", "rationale": "  "}, headline="Three killed in a bombing"
        )

        assert verdict is None

    def test_the_invented_numeral_guard_still_applies(self):
        verdict = news.band_verdict_from_payload(
            {"band": "grave", "rationale": "47 people were killed."},
            headline="Deadly attack reported",
        )

        assert verdict is None

    def test_the_softened_wording_guard_still_applies(self):
        verdict = news.band_verdict_from_payload(
            {"band": "grave", "rationale": "A serious incident occurred."},
            headline="Man dies after attack",
        )

        assert verdict is None

    def test_the_failure_that_motivated_this_cannot_happen(self):
        # #646: qwen2.5:1.5b said "a routine policy or business matter" and
        # scored 0.6 — the confirmed-deaths band. Saying routine now produces a
        # routine value, because the model no longer picks the number.
        verdict = news.band_verdict_from_payload(
            {"band": "routine", "rationale": "A routine policy matter with no harm to anyone."},
            headline="Scientists developing systems for ITER installation",
        )

        assert verdict is not None
        assert verdict.band == "routine"
        assert verdict.value < scale.LETHAL_FLOOR


class TestNumericProtocolUnchanged:
    def test_the_numeric_path_still_produces_its_own_method(self):
        verdict = news.verdict_from_payload(
            {"severity": 0.7, "rationale": "Three people were killed."},
            headline="Three killed in a bombing",
        )

        assert verdict is not None
        assert verdict.method == news.METHOD

    def test_a_band_payload_is_not_accepted_by_the_numeric_parser(self):
        assert (
            news.verdict_from_payload(
                {"band": "grave", "rationale": "Three people were killed."},
                headline="Three killed in a bombing",
            )
            is None
        )


class TestBenchProtocols:
    def _cases(self):
        header = (
            "| headline | model severity | model band | model rationale "
            "| human severity | human band | rationale ok |\n"
            "|---|---|---|---|---|---|---|\n"
        )
        row = "| Three killed in a bombing | 0.7 | grave | three killed | 0.7 | grave | ok |\n"
        return bench.human_cases(header + row)

    def test_the_band_protocol_sends_the_band_prompt(self):
        seen: list[str] = []

        def generate_json(prompt, *, model, keep_alive=None):
            seen.append(prompt)
            return {"band": "grave", "rationale": "Three people were killed."}

        result = bench.bench_model(
            self._cases(), model="candidate", protocol="band", generate_json=generate_json
        )

        assert '"band"' in seen[0]
        assert result["band_agreement"] == 1.0
        assert result["protocol"] == "band"

    def test_the_default_protocol_is_still_the_one_production_runs(self):
        seen: list[str] = []

        def generate_json(prompt, *, model, keep_alive=None):
            seen.append(prompt)
            return {"severity": 0.7, "rationale": "Three people were killed."}

        result = bench.bench_model(self._cases(), model="candidate", generate_json=generate_json)

        assert '"severity"' in seen[0]
        assert result["protocol"] == "number"

    def test_the_report_names_the_protocol_each_row_was_run_under(self):
        results = [
            {
                "model": "candidate",
                "protocol": protocol,
                "attempted": 1,
                "rejected": 0,
                "errors": 0,
                "rejection_rate": 0.0,
                "seconds_per_headline": 1.0,
                "n": 1,
                "n_banded": 1,
                "band_agreement": 0.9,
                "floor_violations": 0,
                "rationale_ok_rate": None,
                "mean_absolute_error": 0.1,
                "passes_gate": True,
            }
            for protocol in ("number", "band")
        ]

        report = bench.render(results, incumbent="incumbent")

        assert "| number |" in report
        assert "| band |" in report
