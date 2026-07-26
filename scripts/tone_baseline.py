"""Measure the bloc tone signal before deciding #155 (#639).

Reads stored rows. Writes nothing, ever — no `--apply`, because there is
nothing to apply. This is a report.

    uv run python scripts/tone_baseline.py --part a              # no model needed
    uv run python scripts/tone_baseline.py --part b --limit 200  # needs Ollama
    uv run python scripts/tone_baseline.py                       # both

**Part A — does tone discriminate?** For stories carried by two or more blocs,
does the lean actually differ between them? VADER scores the valence of words;
`_tone_lean` presents that as a bloc's emotional lean. If blocs almost never
disagree, the feature says the same thing about everyone and comparing them on
it tells a reader nothing — in which case #155's model swap fixes nothing, and
Part B is moot.

**Part B — is VADER right on hard news?** Sample stored headlines, label them
through the local model with an explicit tone rubric, and compare. Disagreeing
headlines are printed, not just counted: the two scorers are answering slightly
different questions (`app/enrichment/tone_llm.py` says how), so the shape of the
disagreement matters more than its size.
"""

import argparse
import logging
import random

from sqlalchemy import select

from app.brain import client
from app.db import session_scope
from app.db_models import EventRow, StoryMemberRow
from app.enrichment import tone_llm
from app.enrichment.tone_baseline import (
    Member,
    measure_agreement,
    measure_discrimination,
)
from app.settings import settings
from app.sources.rss_registry import outlet_country_map


def load_members(session) -> list[Member]:
    """Story members with an origin country and a stored tone label."""
    origins = outlet_country_map()
    rows = session.execute(
        select(StoryMemberRow.story_id, EventRow.source, EventRow.payload).join(
            EventRow, EventRow.id == StoryMemberRow.event_id
        )
    ).all()
    members: list[Member] = []
    for story_id, source, payload in rows:
        country = origins.get(source)
        if not country:
            continue
        members.append(
            Member(
                story_id=story_id,
                origin_country=country,
                label=(payload or {}).get("sentiment_label"),
            )
        )
    return members


def load_headlines(session, *, limit: int, seed: int) -> list[tuple[str, str]]:
    """A random sample of (headline, stored VADER label).

    Sampled in Python against a stable seed rather than ordered by recency: a
    newest-first sample would measure whatever this week's news happens to be,
    and a rerun could not reproduce the same rows.
    """
    rows = session.execute(select(EventRow.payload).where(EventRow.category == "news")).scalars()
    pairs = [
        (title, label)
        for payload in rows
        if (title := (payload or {}).get("title"))
        and (label := (payload or {}).get("sentiment_label"))
    ]
    random.Random(seed).shuffle(pairs)
    return pairs[:limit]


def label_with_model(headline: str, *, model: str) -> str | None:
    """One headline → a model tone label, or None if it could not be read."""
    try:
        # keep_alive holds the model resident across the sample; reloading a 4B
        # per headline would dominate the runtime (same reason as #591's batch).
        payload = client.generate_json(
            tone_llm.build_prompt(headline), model=model, keep_alive="5m"
        )
    except Exception as exc:
        logging.warning("model call failed for %r: %s", headline[:60], exc)
        return None
    return tone_llm.tone_from_payload(payload)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def run_part_a() -> None:
    print("PART A — does bloc tone discriminate?\n")
    with session_scope() as session:
        members = load_members(session)

    report = measure_discrimination(members)
    if report.stories_considered == 0:
        print(
            "  no story has two blocs with enough labelled articles to compare.\n"
            f"  ({report.stories_skipped} story/stories skipped, "
            f"{len(members)} member row(s) read)\n"
            "  nothing can be concluded — run the story clusterer first."
        )
        return

    print(f"  {report.stories_considered} multi-bloc story/stories compared")
    print(f"  {report.stories_skipped} skipped (too few blocs or too few articles)")
    print(
        f"  unanimous across blocs: {report.stories_unanimous} ({_pct(report.unanimous_share)})\n"
    )
    print("  lean distribution overall:")
    for label, count in sorted(report.label_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {label:<10} {count}")

    print("\n  per bloc:")
    for country, counts in sorted(report.per_bloc.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counts.values())
        spread = "  ".join(
            f"{label} {counts.get(label, 0)}" for label in ("negative", "neutral", "positive")
        )
        print(f"    {country:<4} n={total:<5} {spread}")

    share = report.unanimous_share
    if share is not None and share > 0.9:
        print(
            "\n  READ: blocs agree on almost every story. The lean is not comparing "
            "\n  anything — a better model would produce a better number for a "
            "\n  question nobody is asking. #155 closes on this."
        )


def run_part_b(*, limit: int, seed: int, model: str) -> None:
    print("\nPART B — is VADER right on hard news?\n")
    with session_scope() as session:
        sample = load_headlines(session, limit=limit, seed=seed)

    if not sample:
        print("  no news row carries both a title and a stored sentiment label.")
        return

    print(f"  labelling {len(sample)} headline(s) through {model}…\n")
    pairs = [
        (headline, vader, label_with_model(headline, model=model)) for headline, vader in sample
    ]

    report = measure_agreement(pairs)
    if report.compared == 0:
        print("  the model labelled nothing usable — check Ollama is up.")
        return

    print(f"  compared:  {report.compared}")
    print(f"  agreed:    {report.agreed}  ({_pct(report.agreement)})")
    if report.unscored:
        print(f"  unscored:  {report.unscored} (model gave no usable label)")

    print("\n  confusion — rows VADER called X, by what the model called them:")
    for vader_label in ("negative", "neutral", "positive"):
        row = report.confusion_row(vader_label)
        if not row:
            continue
        spread = "  ".join(f"{k} {v}" for k, v in sorted(row.items()))
        print(f"    vader {vader_label:<9} -> {spread}")

    if report.disagreements:
        print(f"\n  disagreements (first {len(report.disagreements)}):")
        for d in report.disagreements:
            print(f"    vader {d.vader:<9} model {d.model:<9} {d.headline[:80]}")
        print(
            "\n  READ: the two scorers answer slightly different questions — VADER "
            "\n  scores word valence, the rubric asks about reporting stance. Grim "
            "\n  facts reported plainly SHOULD split them. Look for disagreements "
            "\n  that are not that."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("a", "b", "both"), default="both")
    parser.add_argument("--limit", type=int, default=200, help="headlines to sample in part B")
    parser.add_argument("--seed", type=int, default=639, help="sample seed, so a rerun repeats")
    parser.add_argument("--model", default=settings.ollama_model)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    if args.part in ("a", "both"):
        run_part_a()
    if args.part in ("b", "both"):
        run_part_b(limit=args.limit, seed=args.seed, model=args.model)


if __name__ == "__main__":
    main()
