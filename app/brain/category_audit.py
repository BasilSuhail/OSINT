"""Category audit sheet — the labelled set that gates a categoriser change (#951).

Emits a sheet of stories with blank category columns. The reviewer fills them
once; `app.brain.category_agreement` scores any candidate model against them.
Same contract as `app.severity.audit`: the model is another fallible
annotator, never a judge, and a blank row is dropped rather than assumed right.

Two deliberate differences from the severity sheet.

**No model answer is shown.** The severity sheet prints the incumbent's verdict
beside the blank column, and validating one model that way is fair. This sheet
exists to compare several, so printing one model's answers would anchor the
labels to that model and hand it an advantage nothing else could earn. The
reviewer labels blind.

**A second question is asked.** `enum ok` records whether the fixed vocabulary
has an honest home for the story at all. Accuracy alone cannot answer that: a
solar eclipse filed `disaster` and a solar eclipse filed `other` are both wrong
in a way no model can fix, because the enum has nowhere right to put it. The
share of rows marked `no` is the evidence for widening the enum, or for
leaving it alone.

The sample is drawn with a fixed seed, so it is reproducible rather than
cherry-picked by whoever wrote the prompt.

    python -m app.brain.category_audit
    make category-audit
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brain import category_agreement
from app.brain.enrich import CATEGORIES, MAX_TITLES
from app.db import get_engine
from app.db_models import EventRow, StoryMemberRow, StoryRow
from app.paths import exports_dir
from app.stories.task import WINDOW_HOURS

#: An unbiased draw over the window. This is what agreement is computed from.
SAMPLE_SIZE: int = 60

#: Extra rows drawn from the stories a reader actually opens, on top of the
#: random block. The window holds thousands of single-filing stories against a
#: few dozen widely-told ones, so a purely random draw is a sheet about
#: stories nobody reads — and the tag on the front page is the one that
#: matters. Same reasoning as the lethal stratum in `app.severity.audit`.
READ_SAMPLE_SIZE: int = 40

#: Fixed seed — same sample every run.
SAMPLE_SEED: int = 951

#: A story needs at least this many independent owners to count as one the
#: reader is likely to meet.
READ_OWNER_FLOOR: int = 8

RANDOM_STRATUM: str = "random"
READ_STRATUM: str = "read"

SHEET_NAME: str = "brain-category-audit-sheet.md"


def build_sheet(rows: list[dict], *, created: str) -> str:
    vocabulary = ", ".join(sorted(CATEGORIES))
    lines = [
        "# Story category human-check sheet",
        "",
        f"Generated {created} · seed {SAMPLE_SEED} · {len(rows)} rows.",
        "",
        "## How to fill this in",
        "",
        "Judge the **headlines**, which are the same ones the model is shown.",
        "No model's answer appears here on purpose — this sheet is used to "
        "compare several, and seeing one of them first would pull the labels "
        "toward it.",
        "",
        f"- **human category** — one of: {vocabulary}. Pick the best fit even "
        "when the fit is poor, then say so in the next column.",
        "- **enum ok** — `yes` if one of those words honestly describes this "
        "story, `no` if you had to force it. Leave a story you would rather "
        "tag something else entirely as `no` and write that word in **would "
        "rather**.",
        "- **would rather** — optional. Only meaningful when `enum ok` is "
        "`no`. The tally of these is the argument for a new tag.",
        "",
        "Leave a row entirely blank to skip it. Blank rows are not counted as "
        "agreement — they are dropped.",
        "",
        "## Two blocks",
        "",
        f"`{RANDOM_STRATUM}` rows are an unbiased draw over the window and are "
        "what agreement is computed from. "
        f"`{READ_STRATUM}` rows are stories told by at least "
        f"{READ_OWNER_FLOOR} independent owners, so the sheet says something "
        "about the tags a reader actually meets — a random draw over this "
        "window is almost entirely stories told once.",
        "",
        "| story | headlines | human category | enum ok | would rather | stratum |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        headlines = " / ".join(t.replace("|", "/") for t in row["titles"])
        lines.append(f"| {row['story_id']} | {headlines} |  |  |  | {row['stratum']} |")
    lines.append("")
    return "\n".join(lines)


def has_human_labels(path: Path) -> bool:
    """Does this sheet already carry a reviewer's answers?

    A filled sheet is hours of hand-labelling and the only evidence any
    categoriser works. The sheet is written to a fixed path, so without this a
    re-run silently discards it.
    """
    if not path.exists():
        return False
    return any(
        row["human_category"] or row["enum_ok"] or row["would_rather"]
        for row in category_agreement.parse_sheet(path.read_text())
    )


def _sample(session: Session, *, now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    stories = list(
        session.execute(
            select(StoryRow.id, StoryRow.owner_count).where(StoryRow.last_seen >= cutoff)
        ).all()
    )
    if not stories:
        return []

    stories.sort(key=lambda s: s.id)
    random.Random(SAMPLE_SEED).shuffle(stories)

    wanted: dict[int, str] = {}
    for story in stories[:SAMPLE_SIZE]:
        wanted[story.id] = RANDOM_STRATUM
    for story in stories:
        if sum(1 for s in wanted.values() if s == READ_STRATUM) >= READ_SAMPLE_SIZE:
            break
        if story.owner_count >= READ_OWNER_FLOOR:
            wanted.setdefault(story.id, READ_STRATUM)

    rows: list[dict] = []
    for story_id, stratum in wanted.items():
        payloads = (
            session.execute(
                select(EventRow.payload)
                .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                .where(StoryMemberRow.story_id == story_id)
                .limit(MAX_TITLES)
            )
            .scalars()
            .all()
        )
        titles = [(p or {}).get("title") or "" for p in payloads]
        titles = [t for t in titles if t]
        if not titles:
            continue
        rows.append({"story_id": story_id, "titles": titles, "stratum": stratum})
    return rows


def _run(*, force: bool = False) -> int:
    exports = exports_dir()
    sheet_path = exports / SHEET_NAME
    if not force and has_human_labels(sheet_path):
        print(
            f"{sheet_path} already contains human labels — refusing to overwrite.\n"
            "Move it aside, or re-run with --force if you meant to discard them."
        )
        return 1

    now = datetime.now(UTC)
    with Session(get_engine()) as session:
        rows = _sample(session, now=now)
    if not rows:
        print("no stories in the window to sample — run the clusterer first")
        return 1

    exports.mkdir(parents=True, exist_ok=True)
    created = now.strftime("%Y-%m-%d %H:%M UTC")
    sheet_path.write_text(build_sheet(rows, created=created))
    print(f"wrote {sheet_path} — {len(rows)} rows, none labelled yet")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a sheet that already carries human labels",
    )
    args = parser.parse_args()
    return _run(force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
