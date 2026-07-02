"""One-shot CLI — compute the coverage-bias table and write the report.

Usage:
    python -m app.coverage.run        # reads ACLED_CSV_DIR from settings
    make coverage
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.coverage.stats import compute_coverage, concentration
from app.labels.acled_loader import load_acled_weekly
from app.settings import settings


def main() -> int:
    if not settings.acled_csv_dir:
        print("ACLED_CSV_DIR is not set — nothing to measure.", file=sys.stderr)
        return 1
    try:
        loaded = load_acled_weekly(settings.acled_csv_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    stats = compute_coverage(loaded.rows)
    tops = concentration(stats)

    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    _write_csv(stats, exports / "coverage-bias.csv")
    (exports / "coverage-bias.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "countries": len(stats),
                "global_events": sum(s["total_events"] for s in stats),
                "top_share": {str(n): round(v, 4) for n, v in tops.items()},
                "stats": stats,
            },
            indent=2,
        )
        + "\n"
    )
    report = _render_markdown(stats, tops)
    (exports / "coverage-bias.md").write_text(report)
    print(report)
    print(f"written: {exports / 'coverage-bias.md'} (+ .json, .csv)")
    return 0


def _write_csv(stats: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats[0].keys()) if stats else [])
        writer.writeheader()
        writer.writerows(stats)


def _render_markdown(stats: list[dict[str, Any]], tops: dict[int, float]) -> str:
    lines = [
        "# Coverage-bias table — how unevenly countries are covered (WS-D)",
        "",
        f"{len(stats)} countries, {sum(s['total_events'] for s in stats):,} events. "
        "Concentration: " + " · ".join(f"top {n} = {share:.1%}" for n, share in tops.items()),
        "",
        "Top 15 by event volume (full table in coverage-bias.csv):",
        "",
        "| country | months | events | events/mo | share | fatal/event | baseline std |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in stats[:15]:
        lines.append(
            f"| {s['country']} | {s['coverage_months']} | {s['total_events']:,} "
            f"| {s['events_per_month']:.1f} | {s['global_share']:.2%} "
            f"| {s['fatalities_per_event']:.2f} | {s['baseline_std']:.1f} |"
        )
    lines += [
        "",
        "`events_per_month` (baseline mean) and `baseline_std` are each country's own "
        "monthly-volume baseline — the normalisation input that judges a loud country "
        "and a quiet country on their own terms (agenda Q4, #282).",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
