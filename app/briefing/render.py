"""Render layer — briefing dict → newsletter-ready markdown (#401).

Pure. The markdown is the email body: plain words first, numbers beside
them, the honesty footer always last. Country codes render as full names.
"""

from __future__ import annotations

from typing import Any

from app.enrichment.country_codes import iso2_to_name


def _country(code: str) -> str:
    return iso2_to_name(code) or code


def render_markdown(briefing: dict[str, Any]) -> str:
    stress = briefing["stress"]
    lines = [
        "# OSINT Weekly Briefing",
        "",
        f"*Week of {briefing['week_start']} → {briefing['week_end']}. Every number below is "
        "measured, versioned, and reproducible — nothing is an editorial opinion.*",
        "",
        f"## World stress level: **{stress['word'].upper()}**",
        "",
        f"Average country stress score {stress['mean']:.3f} for {stress['month']} — each "
        "country judged against its own history, never against another's volume.",
        "",
    ]

    if briefing["movers"]:
        lines += ["**Biggest movers since last month:**", ""]
        for m in briefing["movers"]:
            arrow = "▲" if m["delta"] > 0 else "▼"
            lines.append(
                f"- {arrow} **{_country(m['country'])}** — now {m['latest']:.2f} "
                f"({'+' if m['delta'] > 0 else ''}{m['delta']:.2f})"
            )
        lines.append("")

    lines += ["## Most corroborated stories this week", ""]
    if briefing["top_stories"]:
        for s in briefing["top_stories"]:
            confirmed = (
                f" · sensor-confirmed: {', '.join(c.replace('_', ' ') for c in s['confirmed'])}"
                if s["confirmed"]
                else ""
            )
            lines.append(
                f"- **{s['title']}** — {s['owner_count']} independent owners, "
                f"confidence {s['corroboration']:.2f}{confirmed}"
            )
    else:
        lines.append("- no multi-source stories crossed the bar this week")
    lines.append("")

    lines += ["## Most contested tellings", ""]
    if briefing["contested"]:
        for c in briefing["contested"]:
            groups = " vs ".join(
                f"{_country(code)} x{n}" for code, n in sorted(c["groups"].items())
            )
            lines.append(f"- **{c['title']}** — divergence {c['divergence']:.3f} ({groups})")
    else:
        lines.append("- no cross-country tellings scored this week")
    lines.append("")

    lines += ["## The track record, as of this week", ""]
    if briefing["scoreboard"]:
        lines += [
            "| instrument | horizon | issued | graded | pending | Brier |",
            "|---|---|---|---|---|---|",
        ]
        for line in briefing["scoreboard"]:
            brier = f"{line['brier']:.3f}" if line["brier"] is not None else "—"
            lines.append(
                f"| {line['source']} | {line['horizon_months']}mo | {line['issued']} "
                f"| {line['graded']} | {line['pending']} | {brier} |"
            )
    else:
        lines.append("no forecasts issued yet")
    lines += [
        "",
        "---",
        "",
        "*How to read this: story confidence counts independent owners (wire copies collapse) "
        "and physical-sensor confirmations — hardware cannot spin a narrative. Divergence "
        "measures how differently country blocs word the same event. The track record grades "
        "every forecast in public after it is server-stamped — Brier 0 is clairvoyant, 0.25 is "
        "a coin flip, lower is better. The forecasting instruments are still **on trial**: "
        "their published results to date do not beat naive baselines, and we say so because a "
        "record you can trust is the entire point. Methodology and negatives: the project's "
        "docs/methodology.md and pinned issues.*",
        "",
    ]
    return "\n".join(lines)
