"""Freeze a few minutes of the console into files a static page can serve.

The console needs Postgres, Redis, four Python processes and a Next server. A
reader who wants to know whether any of it is worth their evening should not
have to run all that first, and GitHub Pages will not run any of it at all.

So: one snapshot, taken from a running instance, trimmed to what a map needs,
written as plain JSON. The demo page reads those files and nothing else. It is
frozen by definition, and every screen it draws says so — a demo that lets a
reader believe they are watching live traffic would be worse than no demo.

Run it against a local instance:

    python3 scripts/demo_snapshot.py --api http://127.0.0.1:8000

Standard library only, so it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

#: Fields the demo map actually reads. Everything else — the raw payload a
#: fetcher stored, the relation counts, the audit timestamps — is weight on a
#: page somebody is loading over a phone connection to decide whether to care.
EVENT_FIELDS = (
    "id",
    "source",
    "category",
    "occurred_at",
    "lat",
    "lon",
    "severity",
    "country",
)

#: The handful of payload keys the map's own symbol rules read. Kept explicitly
#: rather than by exclusion: a payload is whatever a fetcher put there, and an
#: allow-list cannot publish a field nobody reviewed.
#:
#: No free text. Titles and headlines are the obvious thing to want on a card
#: and the one thing that cannot go in a file this repository commits: a news
#: headline names people, and those people did not choose to appear in a public
#: repository. The first snapshot taken here carried them and the commit hook
#: refused it, which is the hook doing precisely its job. What is left is
#: codes, numbers and a link back to the source that published it.
PAYLOAD_FIELDS = (
    "event_type",
    "alert_level",
    "magnitude",
    "depth_km",
    "severity_raw",
    "categories",
    "link",
)

AIRCRAFT_FIELDS = (
    "hex",
    "callsign",
    "type",
    "registration",
    "lat",
    "lon",
    "track",
    "alt_ft",
    "speed_kt",
    "kind",
    "role",
    "watch",
)

VESSEL_FIELDS = (
    "mmsi",
    "lat",
    "lon",
    "course",
    "heading",
    "speed_kt",
    "nav_status",
    "category",
    "position_suspect",
)


def fetch(url: str, timeout: float = 60.0) -> object:
    """One GET, or a stated failure. No retries: this is run by a person."""
    request = urllib.request.Request(url, headers={"User-Agent": "OSINT-demo-snapshot/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def pick(row: dict, fields: tuple[str, ...]) -> dict:
    """The named fields that are actually present, and nothing else."""
    return {key: row[key] for key in fields if key in row}


def trim_event(row: dict) -> dict:
    """One event, small enough to ship a thousand of."""
    out = pick(row, EVENT_FIELDS)
    payload = row.get("payload")
    if isinstance(payload, dict):
        kept = pick(payload, PAYLOAD_FIELDS)
        if kept:
            out["payload"] = kept
    return out


#: How many marks the page draws before a laptop notices. Every mark is a DOM
#: element, and the first snapshot taken here held 2,756 of them — a page that
#: stutters while somebody pans is a worse advertisement than no page.
MARK_BUDGET = 700

#: Hazards that are rare and consequential are kept whole; the common ones are
#: thinned. A wildfire feed reports thousands of hot pixels a day and one
#: earthquake is one earthquake, so sampling both at the same rate would drop
#: the quake to keep a hot pixel.
DENSE_SOURCES = ("nasa-firms",)


def thin(rows: list[dict], budget: int, dense: tuple[str, ...] = DENSE_SOURCES) -> list[dict]:
    """At most `budget` rows, dropping the dense feeds first and evenly.

    Evenly rather than by truncation: taking the first N of a list sorted by
    time would show one hour of one continent and call it a day's weather.
    """
    if len(rows) <= budget:
        return rows
    sparse = [r for r in rows if r.get("source") not in dense]
    crowded = [r for r in rows if r.get("source") in dense]
    room = max(0, budget - len(sparse))
    if room == 0:
        step = max(1, len(sparse) // budget)
        return sparse[::step][:budget]
    step = max(1, len(crowded) // room) if room else 1
    return sparse + crowded[::step][:room]


def positioned(rows: list[dict]) -> list[dict]:
    return [r for r in rows if isinstance(r.get("lat"), (int, float)) and r.get("lon") is not None]


def snapshot(api: str, hours: int, limit: int) -> dict:
    """Everything the demo page draws, in one object.

    Each layer is fetched separately and a failure in one is recorded rather
    than fatal: a snapshot with no vessels is still a usable demo, and a
    snapshot that pretends the vessel layer does not exist is not.
    """
    since = (datetime.now(UTC) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    taken_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    missing: list[str] = []
    #: What the console actually held, beside what this file kept. The page
    #: prints both: a demo showing a tenth of the fires without saying so is
    #: making a claim about how many fires there are.
    heard = {"events": 0, "aircraft": 0, "vessels": 0}

    #: Encoded rather than interpolated. An ISO timestamp ends in "+00:00", and
    #: a bare "+" in a query string is a space — which is how the first run of
    #: this script quietly fetched no events at all.
    query = urllib.parse.urlencode({"since": since, "positioned_only": "true", "limit": limit})
    try:
        raw = fetch(f"{api}/events?{query}")
        rows = positioned(raw if isinstance(raw, list) else [])
        heard["events"] = len(rows)
        events = [trim_event(row) for row in thin(rows, MARK_BUDGET)]
    except (urllib.error.URLError, ValueError, TimeoutError):
        events, missing = [], [*missing, "events"]

    try:
        answer = fetch(f"{api}/presence/aircraft")
        flying = answer.get("aircraft", [])
        heard["aircraft"] = len(flying)
        aircraft = [pick(a, AIRCRAFT_FIELDS) for a in flying]
    except (urllib.error.URLError, ValueError, TimeoutError, AttributeError):
        aircraft, missing = [], [*missing, "aircraft"]

    try:
        answer = fetch(f"{api}/presence/vessels")
        afloat = answer.get("vessels", [])
        heard["vessels"] = len(afloat)
        #: Every hull the console does not believe is kept: eight of them in a
        #: thousand is the most interesting thing in the whole snapshot, and
        #: sampling would throw them away first.
        suspect = [v for v in afloat if v.get("position_suspect")]
        ordinary = [v for v in afloat if not v.get("position_suspect")]
        room = max(0, MARK_BUDGET - len(suspect))
        step = max(1, len(ordinary) // room) if room else 1
        kept = suspect + ordinary[::step][:room]
        vessels = [pick(v, VESSEL_FIELDS) for v in kept]
    except (urllib.error.URLError, ValueError, TimeoutError, AttributeError):
        vessels, missing = [], [*missing, "vessels"]

    return {
        "taken_at": taken_at,
        "window_hours": hours,
        "missing": missing,
        #: Said in the file so the page can say it on screen. A demo that
        #: silently shows a tenth of the fires is making a claim about how many
        #: fires there are.
        "mark_budget": MARK_BUDGET,
        #: How many of each the console held when this was taken. Equal to the
        #: kept counts when nothing was thinned.
        "heard": heard,
        "counts": {
            "events": len(events),
            "aircraft": len(aircraft),
            "vessels": len(vessels),
        },
        "events": events,
        "aircraft": aircraft,
        "vessels": vessels,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--out", default="demo/data/snapshot.json")
    args = parser.parse_args(argv)

    data = snapshot(args.api, args.hours, args.limit)
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    #: Compact separators, because this file is downloaded by every visitor and
    #: nobody reads it by hand.
    path.write_text(json.dumps(data, separators=(",", ":")))

    size_kb = path.stat().st_size / 1024
    counts = data["counts"]
    print(f"  wrote {path} — {size_kb:.0f} KB")
    print(
        f"  {counts['events']} events · {counts['aircraft']} aircraft · {counts['vessels']} vessels"
    )
    if data["missing"]:
        print(f"  nothing came back for: {', '.join(data['missing'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
