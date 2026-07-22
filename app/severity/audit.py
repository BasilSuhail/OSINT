"""Audit sheet — the human check that gates LLM severity use (#593).

Emits a markdown sheet of model-graded headlines with blank human columns.
Basil fills them once; `app.severity.agreement` publishes the rate. Until that
rate exists, the LLM verdicts should not be regraded over stored rows and
should not reach the CII — the gate #591 declared, and the same contract #386
set for the validator.

The sample is drawn with a fixed seed, so it is reproducible rather than
cherry-picked by whoever wrote the prompt.

    python -m app.severity.audit
    make severity-audit
"""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import client
from app.db import get_engine
from app.db_models import EventRow
from app.models import Category
from app.settings import settings
from app.severity import news, scale

SAMPLE_SIZE: int = 50
#: Fixed seed — same sample every run.
SAMPLE_SEED: int = 591


def _band_guide() -> list[str]:
    return [
        f"- `{band.name}` {band.lower:.2f} to {band.upper:.2f} — {band.meaning}"
        for band in scale.BANDS
    ]


def build_sheet(rows: list[EventRow], *, created: str) -> str:
    lines = [
        f"# News severity human-check sheet — {news.METHOD}",
        "",
        f"Generated {created} · seed {SAMPLE_SEED} · {len(rows)} rows.",
        "",
        "## The scale",
        "",
        *_band_guide(),
        "",
        "## How to fill this in",
        "",
        "For each row, judge the **headline**, not the model's answer.",
        "",
        "- **human band** — which band the headline belongs in. This is the "
        "column that matters; fill it for every row.",
        "- **human severity** — optional. Only if you want to disagree on the "
        "number within a band.",
        "- **rationale ok** — `ok` if the stated reason is true and blunt, `no` "
        "if it is wrong, softened, or cites something the headline does not say.",
        "",
        "Leave a row entirely blank to skip it. Blank rows are not counted as "
        "agreement — they are dropped.",
        "",
        "| headline | model severity | model band | model rationale "
        "| human severity | human band | rationale ok |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        payload = row.payload or {}
        headline = (payload.get("title") or "").replace("|", "/")
        rationale = (payload.get("severity_rationale") or "").replace("|", "/")
        lines.append(
            f"| {headline} | {row.severity} | {payload.get('severity_band') or '—'} "
            f"| {rationale} |  |  |  |"
        )
    lines.append("")
    return "\n".join(lines)


def _run() -> int:
    """Grade a fixed sample in memory and emit the sheet. Writes nothing.

    Deliberately does not require rows to have been graded already. The point of
    this sheet is to decide whether the model is trustworthy *before* its
    verdicts are written over stored data — requiring `grade_run --apply` first
    would invert that, validating a mutation that had already happened.
    """
    with Session(get_engine()) as session:
        rows = list(
            session.execute(
                select(EventRow).where(EventRow.category == Category.NEWS.value)
            ).scalars()
        )
        rows = [r for r in rows if (r.payload or {}).get("title")]
        if not rows:
            print("no news rows to sample — run an RSS fetch first")
            return 1

        rows.sort(key=lambda r: r.id)
        random.Random(SAMPLE_SEED).shuffle(rows)

        sample: list[EventRow] = []
        for row in rows:
            if len(sample) >= SAMPLE_SIZE:
                break
            headline = (row.payload or {})["title"]
            payload = client.generate_json(
                news.build_prompt(headline), model=settings.ollama_model, keep_alive="5m"
            )
            verdict = news.verdict_from_payload(payload, headline=headline)
            if verdict is None:
                # A guard rejected it. Excluded rather than shown blank: the
                # sheet measures the grades a human can judge, and rejection
                # rate is reported by grade_run.
                continue
            # In-memory only — never committed.
            row.severity = verdict.value
            row.payload = {**(row.payload or {}), **verdict.as_payload()}
            sample.append(row)

        session.expunge_all()

    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    path = exports / "severity-audit-sheet.md"
    path.write_text(build_sheet(sample, created=datetime.now(UTC).date().isoformat()))
    print(f"written: {path} ({len(sample)} rows to hand-check; nothing written to the DB)")
    return 0


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
