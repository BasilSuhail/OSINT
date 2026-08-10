"""The pre-registered decision rule, applied.

`README.md` states the bar: the composite must beat **each** single-domain
baseline on **both** AUROC and AUPR. Stating a rule and leaving a reader to
apply it across a dozen numbers is how a rule stops being one, so the report
prints the verdict rather than the raw comparison alone.

Two states are deliberately distinct. A **FAIL** is evidence the composite did
not clear the bar. **UNDECIDED** is the absence of evidence either way — a
rival that was never scored, or a metric that could not be computed. Collapsing
them would let a missing measurement read as a passed test, which is the exact
error this module exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

#: The metrics the rule names. Both must be won, against every rival.
DECIDING_METRICS: tuple[str, ...] = ("auroc", "aupr")


@dataclass(frozen=True)
class ClaimVerdict:
    """The claim's status for one window and horizon."""

    passed: bool
    undecided: bool
    beaten: list[str] = field(default_factory=list)
    lost_to: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unmeasured: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.undecided:
            reasons = []
            if self.missing:
                reasons.append(f"never scored: {', '.join(self.missing)}")
            if self.unmeasured:
                reasons.append(f"metric unavailable: {', '.join(self.unmeasured)}")
            return f"UNDECIDED — {'; '.join(reasons)}"
        if self.passed:
            return f"PASS — the composite beats {', '.join(self.beaten)} on AUROC and AUPR"
        return f"FAIL — the composite does not beat {', '.join(self.lost_to)}"


def judge_claim(
    rows: Sequence[Mapping[str, object]],
    *,
    composite: str,
    rivals: Sequence[str],
) -> ClaimVerdict:
    """Apply the rule to one window's scored rows.

    `rows` are the head-to-head records — one per baseline, carrying `auroc`
    and `aupr` as `float | None`. `None` means the metric could not be computed
    (a single-class target, an empty window), which `app/baselines/metrics.py`
    reports honestly rather than faking, and which must not read as a win.
    """
    by_name = {str(row["baseline"]): row for row in rows}

    composite_row = by_name.get(composite)
    missing = [name for name in rivals if name not in by_name]
    if composite_row is None:
        missing = [composite, *missing]

    unmeasured: list[str] = []
    if composite_row is not None:
        unmeasured = [
            f"{composite} {metric}"
            for metric in DECIDING_METRICS
            if composite_row.get(metric) is None
        ]

    if missing or unmeasured:
        return ClaimVerdict(
            passed=False,
            undecided=True,
            missing=missing,
            unmeasured=unmeasured,
        )

    assert composite_row is not None  # narrowed by the `missing` check above

    beaten: list[str] = []
    lost_to: list[str] = []
    undecided_against: list[str] = []
    for name in rivals:
        rival = by_name[name]
        if any(rival.get(metric) is None for metric in DECIDING_METRICS):
            undecided_against.append(name)
            continue
        # A tie is not a win: equal performance is two extra data domains
        # bought and nothing returned for them.
        if all(
            float(composite_row[metric]) > float(rival[metric])  # type: ignore[arg-type]
            for metric in DECIDING_METRICS
        ):
            beaten.append(name)
        else:
            lost_to.append(name)

    if undecided_against and not lost_to:
        return ClaimVerdict(
            passed=False,
            undecided=True,
            beaten=beaten,
            unmeasured=[f"{name} metric" for name in undecided_against],
        )

    return ClaimVerdict(
        passed=not lost_to,
        undecided=False,
        beaten=beaten,
        lost_to=lost_to,
    )
