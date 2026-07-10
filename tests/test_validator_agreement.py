"""Tests for `app.validator.agreement` — sheet parsing + rates (WS-G step 2, #386)."""

from __future__ import annotations

from app.validator.agreement import compute_agreement, parse_sheet

HEADER = (
    "| story | model countries | model event | model casualties "
    "| human countries | human event | human casualties |\n"
    "|---|---|---|---|---|---|---|\n"
)


def test_parse_sheet_reads_filled_rows_only() -> None:
    sheet = HEADER + (
        "| Quake story | TR | earthquake | 12 | ok | ok | ok |\n"
        "| Unfilled row | GB | none | — |  |  |  |\n"
        "| Corrected row | VE | earthquake | 3811 | ok | ok | 3342 |\n"
    )
    rows = parse_sheet(sheet)
    assert len(rows) == 2  # unfilled row is uncounted, never assumed
    assert rows[0]["human"] == {"countries": "ok", "event": "ok", "casualties": "ok"}
    assert rows[1]["human"]["casualties"] == "3342"


def test_compute_agreement_per_field_and_overall() -> None:
    rows = parse_sheet(
        HEADER
        + "| A | TR | earthquake | 12 | ok | ok | ok |\n"
        + "| B | VE | earthquake | 3811 | ok | ok | 3342 |\n"
        + "| C | GB | none | — | FR | ok | ok |\n"
        + "| D | US | disaster | — | ok | none | ok |\n"
    )
    rates = compute_agreement(rows)
    assert rates["n"] == 4
    assert rates["countries"] == 0.75  # C corrected
    assert rates["event"] == 0.75  # D corrected
    assert rates["casualties"] == 0.75  # B corrected
    assert rates["all_fields"] == 0.25  # only A fully agreed


def test_compute_agreement_empty_sheet() -> None:
    assert compute_agreement([]) is None
