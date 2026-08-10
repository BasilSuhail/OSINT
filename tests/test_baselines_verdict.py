"""Tests for the pre-registered decision rule.

`README.md` states the bar precisely: the composite must beat **each** of the
single-domain baselines on **both** AUROC and AUPR. That is a verdict, not a
table to read off, and a reader who has to compare twelve numbers by eye is a
reader who will eventually get it wrong in the direction they were hoping for.
"""

from __future__ import annotations

from app.baselines.verdict import ClaimVerdict, judge_claim


def _row(baseline: str, *, auroc: float | None, aupr: float | None) -> dict:
    return {"baseline": baseline, "auroc": auroc, "aupr": aupr}


COMPOSITE = "B6 composite"
RIVALS = ("B3 geopolitical only", "B4 market only", "B5 hazard only")


class TestJudgeClaim:
    def test_passes_only_when_it_beats_every_rival_on_both_metrics(self) -> None:
        rows = [
            _row(COMPOSITE, auroc=0.80, aupr=0.50),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.40),
            _row("B4 market only", auroc=0.60, aupr=0.30),
            _row("B5 hazard only", auroc=0.65, aupr=0.35),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert verdict.passed is True
        assert verdict.beaten == list(RIVALS)
        assert verdict.lost_to == []

    def test_losing_on_one_metric_to_one_rival_fails_the_whole_claim(self) -> None:
        # Wins on AUROC everywhere, loses AUPR to hazard alone. The rule says
        # both metrics, so this is a failure — and the honest report is the
        # one that says so rather than leading with the AUROC win.
        rows = [
            _row(COMPOSITE, auroc=0.80, aupr=0.30),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.20),
            _row("B4 market only", auroc=0.60, aupr=0.25),
            _row("B5 hazard only", auroc=0.65, aupr=0.45),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert verdict.passed is False
        assert verdict.lost_to == ["B5 hazard only"]

    def test_a_tie_is_not_a_win(self) -> None:
        # "Better than" means better. Equal performance is the composite
        # buying two extra data domains and returning nothing for them.
        rows = [
            _row(COMPOSITE, auroc=0.70, aupr=0.40),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.40),
            _row("B4 market only", auroc=0.50, aupr=0.10),
            _row("B5 hazard only", auroc=0.50, aupr=0.10),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert verdict.passed is False
        assert verdict.lost_to == ["B3 geopolitical only"]

    def test_an_unmeasurable_metric_is_not_a_pass(self) -> None:
        # `metrics.py` returns None for degenerate inputs — a single-class
        # target, an empty window. None is missing evidence, and missing
        # evidence has to read as "not shown", never as "cleared the bar".
        rows = [
            _row(COMPOSITE, auroc=0.80, aupr=None),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.40),
            _row("B4 market only", auroc=0.60, aupr=0.30),
            _row("B5 hazard only", auroc=0.65, aupr=0.35),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert verdict.passed is False
        assert verdict.undecided is True

    def test_a_missing_rival_leaves_the_claim_undecided(self) -> None:
        # The state this whole change exists to end: with B3/B4/B5 absent,
        # a composite that beat the no-skill trio could look like a win. It
        # was never the claim, and the report must not let it read as one.
        rows = [
            _row(COMPOSITE, auroc=0.80, aupr=0.50),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.40),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert verdict.passed is False
        assert verdict.undecided is True
        assert "B4 market only" in verdict.missing

    def test_verdict_reads_as_a_sentence(self) -> None:
        rows = [
            _row(COMPOSITE, auroc=0.51, aupr=0.10),
            _row("B3 geopolitical only", auroc=0.70, aupr=0.40),
            _row("B4 market only", auroc=0.60, aupr=0.30),
            _row("B5 hazard only", auroc=0.65, aupr=0.35),
        ]

        verdict = judge_claim(rows, composite=COMPOSITE, rivals=RIVALS)

        assert isinstance(verdict, ClaimVerdict)
        assert verdict.summary.startswith("FAIL")
        assert "B3 geopolitical only" in verdict.summary
