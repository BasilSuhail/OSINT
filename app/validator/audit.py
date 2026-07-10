"""Audit sheet — the ~50-story human check that gates all downstream use.

Emits a markdown sheet of model-extracted claims with blank human columns.
Basil fills the human columns once; a later WS-G step computes and publishes
the agreement rate. Until then the validator's rows feed nothing.

Usage:
    python -m app.validator.audit
    make validator-audit
"""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.db_models import StoryClaimRow, StoryRow
from app.validator.claims import METHOD_VERSION

SAMPLE_SIZE: int = 50
#: Fixed seed — the sample is reproducible, not cherry-picked.
SAMPLE_SEED: int = 361


def _run() -> int:
    with Session(get_engine()) as session:
        rows = session.execute(
            select(StoryClaimRow, StoryRow.title)
            .join(StoryRow, StoryRow.id == StoryClaimRow.story_id)
            .where(StoryClaimRow.method_version == METHOD_VERSION)
        ).all()

    if not rows:
        print("no claims extracted yet — run `make validator` first")
        return 1

    sample = sorted(rows, key=lambda pair: pair[0].story_id)
    random.Random(SAMPLE_SEED).shuffle(sample)
    sample = sample[:SAMPLE_SIZE]

    lines = [
        f"# Validator human-check sheet — {METHOD_VERSION}",
        "",
        f"Generated {datetime.now(UTC).date().isoformat()} · seed {SAMPLE_SEED} · "
        f"{len(sample)} of {len(rows)} extracted stories.",
        "",
        "Fill the three `human …` columns (`ok` / correction). Agreement gets "
        "computed and published by the next WS-G step; until then the model's "
        "rows feed nothing.",
        "",
        "| story | model countries | model event | model casualties "
        "| human countries | human event | human casualties |",
        "|---|---|---|---|---|---|---|",
    ]
    for claim, title in sample:
        claims = claim.claims
        countries = " ".join(claims.get("countries") or []) or "—"
        casualties = claims.get("casualties")
        lines.append(
            f"| {title} | {countries} | {claims.get('event_type')} "
            f"| {casualties if casualties is not None else '—'} |  |  |  |"
        )
    lines.append("")

    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    path = exports / "validator-audit-sheet.md"
    path.write_text("\n".join(lines))
    print(f"written: {path} ({len(sample)} rows to hand-check)")
    return 0


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
