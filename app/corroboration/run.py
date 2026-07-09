"""One-shot CLI — run sensor cross-checks and show the verdict board.

Usage:
    python -m app.corroboration.run
    make sensor-checks
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corroboration.task import _sensor_checks_body
from app.db import get_engine
from app.db_models import StoryRow, StorySensorCheckRow


def _run() -> int:
    counters = _sensor_checks_body()

    since = datetime.now(UTC) - timedelta(hours=24)
    with Session(get_engine()) as session:
        rows = session.execute(
            select(StorySensorCheckRow, StoryRow.title, StoryRow.owner_count)
            .join(StoryRow, StoryRow.id == StorySensorCheckRow.story_id)
            .where(StorySensorCheckRow.checked_at >= since)
            .order_by(StorySensorCheckRow.verdict, StorySensorCheckRow.claim_type)
        ).all()
        checks = [
            {
                "story_id": check.story_id,
                "claim": check.claim_type,
                "verdict": check.verdict,
                "owners": owner_count,
                "evidence": check.evidence,
                "title": title,
            }
            for check, title, owner_count in rows
        ]

    report = _render_markdown(counters, checks)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "sensor-checks-report.md").write_text(report)
    (exports / "sensor-checks-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "run": counters,
                "checks_24h": checks,
            },
            indent=2,
        )
        + "\n"
    )
    print(report)
    print(f"written: {exports / 'sensor-checks-report.md'} (+ .json)")
    return 0


def _render_markdown(counters: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    lines = [
        "# Sensor cross-checks — claim vs machine (WS-C step 3)",
        "",
        f"This run: {counters['stories']} stories with claims, {counters['claims']} claims, "
        f"{counters['confirmed']} confirmed, {counters['unconfirmed']} unconfirmed, "
        f"{counters['kept_confirmed']} previously confirmed kept.",
        "",
        "Checks touched in the last 24 h:",
        "",
        "| verdict | claim | owners | story |",
        "|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['verdict']} | {check['claim']} | {check['owners']} | {check['title']} |"
        )
    lines += [
        "",
        "Rules are declared constants (`sensor-rules-v1.0`): earthquake→USGS, "
        "wildfire→FIRMS, disaster→GDACS, market crash→market drawdown. "
        "`confirmed` never downgrades — evidence snapshots outlive sensor retention.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rc = _run()
    if rc != 0:
        raise SystemExit(f"sensor-checks: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
