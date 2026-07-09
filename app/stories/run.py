"""One-shot CLI — cluster the news window and show top multi-outlet stories.

Usage:
    python -m app.stories.run
    make stories
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
from app.db_models import StoryRow
from app.stories.task import _cluster_stories_body


def _run() -> int:
    counters = _cluster_stories_body()

    since = datetime.now(UTC) - timedelta(hours=24)
    with Session(get_engine()) as session:
        top = session.execute(
            select(StoryRow)
            .where(StoryRow.last_seen >= since)
            .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
            .limit(15)
        ).scalars()
        top_rows = [
            {
                "title": row.title,
                "owners": row.owner_count,
                "outlets": row.outlet_count,
                "members": row.member_count,
            }
            for row in top
        ]

    report = _render_markdown(counters, top_rows)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "stories-report.md").write_text(report)
    (exports / "stories-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "run": counters,
                "top_stories_24h": top_rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(report)
    print(f"written: {exports / 'stories-report.md'} (+ .json)")
    return 0


def _render_markdown(counters: dict[str, Any], top_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Story clusters — one row per real-world story (WS-A)",
        "",
        f"This run: {counters['window_news']} news events in window, "
        f"{counters['newly_assigned']} newly assigned, "
        f"{counters['new_stories']} new stories.",
        "",
        "Top stories of the last 24 h by outlet count:",
        "",
        "| owners | outlets | members | story |",
        "|---|---|---|---|",
    ]
    for row in top_rows:
        lines.append(f"| {row['owners']} | {row['outlets']} | {row['members']} | {row['title']} |")
    lines += [
        "",
        "`owners` = distinct *independent* tellers (#355) — the WS-C corroboration input; "
        "`outlets` = distinct feeds (wire copies and co-owned feeds collapse into one owner). "
        "Assignments are append-only; clusters build over the rolling 72 h window.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("stories"):
        rc = _run()
        if rc != 0:
            raise SystemExit(f"stories: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
