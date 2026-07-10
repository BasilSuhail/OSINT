"""One-shot CLI — run the validator batch once and show what it extracted.

Usage:
    python -m app.validator.run
    make validator
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.db_models import StoryClaimRow, StoryRow
from app.validator.task import _validator_body


def _run() -> int:
    counters = _validator_body()

    since = datetime.now(UTC) - timedelta(hours=24)
    with Session(get_engine()) as session:
        rows = session.execute(
            select(StoryClaimRow, StoryRow.title)
            .join(StoryRow, StoryRow.id == StoryClaimRow.story_id)
            .where(StoryClaimRow.extracted_at >= since)
            .order_by(StoryClaimRow.extracted_at.desc())
            .limit(25)
        ).all()
        extracted = [
            {
                "story_id": row.story_id,
                "claims": row.claims,
                "model": row.model,
                "title": title,
            }
            for row, title in rows
        ]

    report = _render_markdown(counters, extracted)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "validator-report.md").write_text(report)
    (exports / "validator-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "run": counters,
                "extracted_24h": extracted,
            },
            indent=2,
        )
        + "\n"
    )
    print(report)
    print(f"written: {exports / 'validator-report.md'} (+ .json)")
    return 0


def _render_markdown(counters: dict[str, Any], extracted: list[dict[str, Any]]) -> str:
    lines = [
        "# Validator — local-LLM claim extraction (WS-G step 1)",
        "",
        f"This run: {counters['window_stories']} stories in window, "
        f"{counters['extracted']} extracted, {counters['skipped_existing']} already done, "
        f"{counters['failed']} failed.",
        "",
        "Latest extractions:",
        "",
        "| countries | event type | casualties | story |",
        "|---|---|---|---|",
    ]
    for row in extracted:
        claims = row["claims"]
        countries = " ".join(claims.get("countries") or []) or "—"
        casualties = claims.get("casualties")
        lines.append(
            f"| {countries} | {claims.get('event_type')} "
            f"| {casualties if casualties is not None else '—'} | {row['title']} |"
        )
    lines += [
        "",
        "The model is *another noisy annotator*, never a judge: rows carry model + "
        "prompt version, and nothing downstream consumes them until agreement with "
        "the human-checked sample (`make validator-audit`) is measured and published.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rc = _run()
    if rc != 0:
        raise SystemExit(f"validator: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
