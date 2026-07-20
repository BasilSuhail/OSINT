"""Sweep stored gists for invented figures (#553).

#514 stopped new gists carrying numbers their headlines lack; the rows written
before that check existed are still live, and the Q&A model can quote any of
them. This finds them and deletes them. A deleted gist is not a hole for long:
a story still inside the enrich window is picked up on the next pass and
re-gisted under the #514 check. Stories older than that window lose their gist
for good, which is the right trade — no gist degrades gracefully, an invented
casualty figure does not.

Grounding here reads *every* member headline, not just the MAX_TITLES the
prompt carried. That is deliberately more forgiving than the live check: this
path deletes rows, so a figure the model could not have seen but that some
member headline happens to carry is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.brain import enrich, numerals
from app.db_models import EventRow, StoryGistRow, StoryMemberRow


@dataclass(frozen=True)
class Offender:
    """A stored gist asserting figures none of its headlines carry."""

    gist_id: int
    story_id: int
    gist: str
    figures: list[float]
    titles: list[str]


def _titles_by_story(session: Session, story_ids: list[int]) -> dict[int, list[str]]:
    if not story_ids:
        return {}
    rows = session.execute(
        select(StoryMemberRow.story_id, EventRow.payload)
        .join(EventRow, EventRow.id == StoryMemberRow.event_id)
        .where(StoryMemberRow.story_id.in_(story_ids))
    ).all()
    titles: dict[int, list[str]] = {}
    for story_id, payload in rows:
        title = (payload or {}).get("title") or ""
        if title:
            titles.setdefault(story_id, []).append(title)
    return titles


def find_offenders(session: Session) -> list[Offender]:
    """Current-version gists carrying figures their member headlines lack."""
    rows = session.execute(
        select(StoryGistRow.id, StoryGistRow.story_id, StoryGistRow.gist).where(
            StoryGistRow.method_version == enrich.METHOD_VERSION
        )
    ).all()
    titles = _titles_by_story(session, [story_id for _, story_id, _ in rows])

    offenders: list[Offender] = []
    for gist_id, story_id, gist in rows:
        story_titles = titles.get(story_id, [])
        figures = numerals.unsupported_numerals(gist or "", story_titles)
        if figures:
            offenders.append(
                Offender(
                    gist_id=gist_id,
                    story_id=story_id,
                    gist=gist or "",
                    figures=figures,
                    titles=story_titles,
                )
            )
    return offenders


def delete_offenders(session: Session, offenders: list[Offender]) -> int:
    """Drop the flagged rows. Returns how many were removed."""
    if not offenders:
        return 0
    result = session.execute(
        delete(StoryGistRow).where(StoryGistRow.id.in_([o.gist_id for o in offenders]))
    )
    session.commit()
    return result.rowcount
