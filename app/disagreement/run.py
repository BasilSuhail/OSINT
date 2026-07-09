"""One-shot CLI — score telling divergence and show the most contested stories.

Usage:
    python -m app.disagreement.run
    make disagreement
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
from app.db_models import StoryDisagreementRow, StoryRow
from app.disagreement.task import _disagreement_body


def _run() -> int:
    counters = _disagreement_body()

    since = datetime.now(UTC) - timedelta(hours=24)
    with Session(get_engine()) as session:
        rows = session.execute(
            select(StoryDisagreementRow, StoryRow.title)
            .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
            .where(StoryDisagreementRow.computed_at >= since)
            .order_by(StoryDisagreementRow.divergence.desc())
            .limit(20)
        ).all()
        contested = [
            {
                "story_id": row.story_id,
                "divergence": round(row.divergence, 4),
                "groups": row.components["groups"],
                "title": title,
            }
            for row, title in rows
        ]

    report = _render_markdown(counters, contested)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "disagreement-report.md").write_text(report)
    (exports / "disagreement-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "run": counters,
                "most_contested_24h": contested,
            },
            indent=2,
        )
        + "\n"
    )
    print(report)
    print(f"written: {exports / 'disagreement-report.md'} (+ .json)")
    return 0


def _render_markdown(counters: dict[str, Any], contested: list[dict[str, Any]]) -> str:
    lines = [
        "# Telling divergence — who disagrees about what (WS-B step 2)",
        "",
        f"This run: {counters['stories']} stories in window, {counters['scored']} scored, "
        f"{counters['single_group']} single-country (no cross-country telling).",
        "",
        "Most contested stories of the last 24 h:",
        "",
        "| divergence | country groups | story |",
        "|---|---|---|",
    ]
    for row in contested:
        groups = " ".join(f"{c}:{n}" for c, n in row["groups"].items())
        lines.append(f"| {row['divergence']:.3f} | {groups} | {row['title']} |")
    lines += [
        "",
        "`divergence` (disagreement-v1.0) = mean pairwise cosine distance between "
        "country-group TF-IDF centroids over the story's member titles. Groups are "
        "outlet *origin* countries (#368). High = the same event is being told in "
        "very different words by different countries.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rc = _run()
    if rc != 0:
        raise SystemExit(f"disagreement: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
