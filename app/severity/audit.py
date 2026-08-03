"""Audit sheet — the human check that gates LLM severity use (#593).

Emits a markdown sheet of model-graded headlines with blank human columns.
The reviewer fills them once; `app.severity.agreement` publishes the rate. Until that
rate exists, the LLM verdicts should not be regraded over stored rows and
should not reach the CII — the gate #591 declared, and the same contract #386
set for the validator.

The sample is drawn with a fixed seed, so it is reproducible rather than
cherry-picked by whoever wrote the prompt.

    python -m app.severity.audit
    make severity-audit
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import client
from app.db import get_engine
from app.db_models import EventRow
from app.models import Category
from app.paths import exports_dir
from app.settings import settings
from app.severity import agreement, news, scale

SAMPLE_SIZE: int = 50
#: Fixed seed — same sample every run.
SAMPLE_SEED: int = 591

#: Extra rows drawn from headlines that look fatal, on top of the random block
#: (#665). The random block yielded four lethal rows out of fifty, so every
#: "zero missed deaths" figure this project has published — the one #593 said
#: to read first — rested on four headlines. Random sampling cannot fix that
#: without asking a human to grade hundreds of rows, because news is mostly
#: not fatal.
LETHAL_SAMPLE_SIZE: int = 30

#: Stratum labels, carried in the sheet so nobody has to reconstruct later
#: which block a row came from.
RANDOM_STRATUM: str = "random"
LETHAL_STRATUM: str = "lethal"


def looks_lethal(headline: str) -> bool:
    """Does this headline claim a death, by a rule the model had no part in?

    This is the whole design of #665. The obvious way to find lethal headlines
    is to ask the model which ones it graded `grave` — and that would destroy
    the metric it is meant to repair. A floor violation is "the human says
    someone died and the model scored it below 0.60", so selecting on the
    model's own verdict excludes exactly those rows by construction, and the
    sheet would measure precision while claiming to measure missed harm.

    `news._LETHAL_WORDS` owes nothing to the model — it is the fixed list the
    ingest-path fallback uses. It is still *enriched*, never exhaustive: a
    death can be reported without any of its words, as "Body found in river"
    or "Toll rises to nine" do, so the random block stays to cover what this
    cannot see.

    Matched through the same word-boundary pattern the fallback uses, so
    the sheet is not filled with headlines whose only claim to death is the
    word *deadline* (#739).
    """
    return news._pattern(news._LETHAL_WORDS).search(headline.lower()) is not None


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
        "## Two blocks",
        "",
        f"`{RANDOM_STRATUM}` rows are an unbiased draw and are what band "
        "agreement is computed from. `"
        f"{LETHAL_STRATUM}` rows were picked because the headline carries a "
        "death word, so the floor check has more than a handful of rows to "
        "stand on (#665). They are selected by keyword, never by what the "
        "model said — picking on the model's own verdict would exclude the "
        "misses the floor metric exists to count.",
        "",
        "| headline | model severity | model band | model rationale "
        "| human severity | human band | rationale ok | stratum |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        payload = row.payload or {}
        headline = (payload.get("title") or "").replace("|", "/")
        rationale = (payload.get("severity_rationale") or "").replace("|", "/")
        stratum = LETHAL_STRATUM if looks_lethal(headline) else RANDOM_STRATUM
        lines.append(
            f"| {headline} | {row.severity} | {payload.get('severity_band') or '—'} "
            f"| {rationale} |  |  |  | {stratum} |"
        )
    lines.append("")
    return "\n".join(lines)


def has_human_grades(path: Path) -> bool:
    """Does this sheet already carry a human's answers?

    A filled sheet is hours of hand-grading and the only evidence the grader
    works. `make severity-audit` writes to a fixed path, so without this a
    re-run silently discards it.
    """
    if not path.exists():
        return False
    return any(
        row["human_band"] or row["human_severity"] is not None or row["rationale_ok"]
        for row in agreement.parse_sheet(path.read_text())
    )


def _run(*, force: bool = False) -> int:
    """Grade a fixed sample in memory and emit the sheet. Writes nothing.

    Deliberately does not require rows to have been graded already. The point of
    this sheet is to decide whether the model is trustworthy *before* its
    verdicts are written over stored data — requiring `grade_run --apply` first
    would invert that, validating a mutation that had already happened.
    """
    exports = exports_dir()
    sheet_path = exports / "severity-audit-sheet.md"
    if not force and has_human_grades(sheet_path):
        # Checked before a single model call: grading the sample takes minutes,
        # and refusing afterwards would burn all of them to say no. The filled
        # sheet is hours of hand-grading and the only evidence the grader works
        # — the very thing #665 exists to give more of.
        print(
            f"{sheet_path} already contains human grades — refusing to overwrite.\n"
            "Move it aside, or re-run with --force if you meant to discard them."
        )
        return 1

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

        # Two blocks. The random one is the sheet as it always was, and is what
        # band agreement is computed from. The lethal one is drawn from rows the
        # keyword rule flags, so the floor metric stops resting on four rows
        # (#665) — and it is drawn from the same shuffled order, so it stays
        # reproducible rather than cherry-picked.
        lethal_pool = [r for r in rows if looks_lethal((r.payload or {})["title"])]
        wanted = {id(r): RANDOM_STRATUM for r in rows[:SAMPLE_SIZE]}
        for row in lethal_pool:
            if len([s for s in wanted.values() if s == LETHAL_STRATUM]) >= LETHAL_SAMPLE_SIZE:
                break
            wanted.setdefault(id(row), LETHAL_STRATUM)
        candidates = [r for r in rows if id(r) in wanted]

        sample: list[EventRow] = []
        for row in candidates:
            headline = (row.payload or {})["title"]
            payload = client.generate_json(
                news.build_prompt(headline), model=settings.severity_model, keep_alive="5m"
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

    exports.mkdir(parents=True, exist_ok=True)
    sheet_path.write_text(build_sheet(sample, created=datetime.now(UTC).date().isoformat()))
    print(f"written: {sheet_path} ({len(sample)} rows to hand-check; nothing written to the DB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a sheet that already has human grades in it",
    )
    return _run(force=parser.parse_args().force)


if __name__ == "__main__":
    raise SystemExit(main())
