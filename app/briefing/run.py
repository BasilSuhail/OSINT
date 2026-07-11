"""One-shot CLI — generate the weekly briefing now.

Usage:
    python -m app.briefing.run
    make briefing
"""

from __future__ import annotations

import os
from pathlib import Path

from app.briefing.task import _briefing_body


def main() -> int:
    counters = _briefing_body()
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    print((exports / "weekly-briefing.md").read_text())
    print(
        f"written: {exports / 'weekly-briefing.md'} (+ .json) · "
        f"{counters['top_stories']} stories · {counters['contested']} contested · "
        f"{counters['movers']} movers · {counters['scoreboard_lines']} scoreboard lines"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
