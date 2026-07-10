"""Agreement layer — the filled human sheet → published rates (WS-G step 2, #386).

The sheet contract (from `app.validator.audit`): three human columns per row;
`ok` (case-insensitive) means the model's value was right, anything else is
the human's correction, an entirely blank human side leaves the row
uncounted — never assumed. The published rate is the gate step 1 declared:
until it exists, validator rows feed nothing.

Usage:
    python -m app.validator.agreement
    make validator-agreement
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIELDS: tuple[str, ...] = ("countries", "event", "casualties")


def parse_sheet(text: str) -> list[dict[str, Any]]:
    """Filled rows only: story, model triple, human triple."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or cells[0] == "story":
            continue
        human = dict(zip(FIELDS, cells[4:7], strict=True))
        if not any(human.values()):
            continue
        rows.append(
            {
                "story": cells[0],
                "model": dict(zip(FIELDS, cells[1:4], strict=True)),
                "human": human,
            }
        )
    return rows


def compute_agreement(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Per-field + all-fields agreement over the filled rows; None when empty."""
    if not rows:
        return None
    rates: dict[str, Any] = {"n": len(rows)}
    full_agree = 0
    per_field = {field: 0 for field in FIELDS}
    for row in rows:
        agreements = {field: row["human"][field].lower() == "ok" for field in FIELDS}
        for field, agreed in agreements.items():
            per_field[field] += int(agreed)
        full_agree += int(all(agreements.values()))
    for field in FIELDS:
        rates[field] = per_field[field] / len(rows)
    rates["all_fields"] = full_agree / len(rows)
    return rates


def _run() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    sheet_path = exports / "validator-audit-sheet.md"
    if not sheet_path.exists():
        print("no audit sheet found — run `make validator-audit` first")
        return 1

    rows = parse_sheet(sheet_path.read_text())
    rates = compute_agreement(rows)
    if rates is None:
        print(
            "audit sheet has no filled human columns yet — fill the sheet, then rerun. "
            "Until then the validator's rows feed nothing."
        )
        return 1

    lines = [
        "# Validator agreement — the model vs the human sample (WS-G step 2)",
        "",
        f"Generated {datetime.now(UTC).date().isoformat()} from {rates['n']} hand-checked rows.",
        "",
        "| field | agreement |",
        "|---|---|",
        *(f"| {field} | {rates[field]:.1%} |" for field in FIELDS),
        f"| **all fields** | **{rates['all_fields']:.1%}** |",
        "",
        "This is the annotator's published error rate. Downstream use of validator "
        "rows (WS-C structured claims, WS-B facts-vs-framing) is only defensible "
        "for fields whose agreement clears the bar the consuming analysis declares.",
        "",
    ]
    report = "\n".join(lines)
    (exports / "validator-agreement.md").write_text(report)
    print(report)
    print(f"written: {exports / 'validator-agreement.md'}")
    return 0


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
