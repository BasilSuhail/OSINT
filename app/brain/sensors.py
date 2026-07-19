"""Structured sensor retrieval for Q&A (#507).

Story clustering takes ``category == "news"`` and Q&A retrieves from
``StoryRow``, so until now the brain could only see what an outlet wrote about.
Earthquakes, floods, wildfires, GDELT and cyber events — the large majority of
what the app ingests — were invisible to it. "Were there any big earthquakes?"
could only be answered from an article that happened to mention one.

Retrieval here is **structured, not semantic**. Sensor events are
attribute-shaped: a type, a magnitude, a place, a time. Matching them is
category filtering with a severity sort, so no embeddings, no model call and no
new table are involved — a question naming a hazard selects that hazard's rows
directly.

Volume is handled in two parts. The event list is capped, because a model handed
four hundred quakes writes worse answers than one handed twelve; alongside it
``build_sensor_summary`` returns per-kind counts for the whole window, so the
answer can say "40 quakes, the largest 6.4" without reading forty rows.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Float, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.enrichment.country import country_from_text, country_name

#: How far back sensor retrieval looks. Matches the story window: an answer
#: should not mix last week's quakes with today's headlines.
SENSOR_WINDOW_H = 72

#: Most events handed to the model. Counts carry the totals beyond this.
#:
#: Kept deliberately small: the Q&A prompt already runs over the 2048-token
#: window the local model is capped at (#384), so every row here costs
#: instructions off the top of the prompt. Six readings plus totals answers
#: "what was biggest" and "how many" without crowding the rules out.
SENSOR_LIMIT = 6


#: Question word → sensor kind. Plural folding happens at match time, so only
#: singular stems belong here. Kinds are the vocabulary the answer speaks in,
#: which is why they are words ("earthquake") rather than feed codes ("EQ").
_KIND_TERMS: dict[str, frozenset[str]] = {
    "earthquake": frozenset({"earthquake", "quake", "seismic", "tremor", "aftershock"}),
    "flood": frozenset({"flood", "flooding", "inundation", "deluge"}),
    "cyclone": frozenset({"cyclone", "hurricane", "typhoon", "storm"}),
    "wildfire": frozenset({"wildfire", "bushfire", "firestorm"}),
    "volcano": frozenset({"volcano", "volcanic", "eruption"}),
    "drought": frozenset({"drought"}),
    "cyber": frozenset({"cyber", "malware", "botnet", "ransomware", "phishing", "c2"}),
}

#: Questions asking about hazards generally, with no specific type named.
_GENERIC_HAZARD_TERMS = frozenset({"hazard", "disaster", "catastrophe", "emergency", "sensor"})

_GENERIC_HAZARD_KINDS = ("earthquake", "flood", "cyclone", "wildfire", "volcano", "drought")

#: GDACS publishes its type as a two-letter code in the payload.
_GDACS_CODE_TO_KIND: dict[str, str] = {
    "EQ": "earthquake",
    "FL": "flood",
    "TC": "cyclone",
    "WF": "wildfire",
    "VO": "volcano",
    "DR": "drought",
}
_KIND_TO_GDACS_CODE = {kind: code for code, kind in _GDACS_CODE_TO_KIND.items()}

_TERM_RE = re.compile(r"[a-z][a-z0-9'-]+")


def question_kinds(question: str | None) -> frozenset[str]:
    """Sensor kinds a question explicitly asks about.

    Deterministic lexicon lookup with the same naive plural folding the story
    intent gate uses. An empty set means no sensor intent, and retrieval returns
    nothing rather than padding the context with unrelated readings.
    """
    if not question:
        return frozenset()
    kinds: set[str] = set()
    generic = False
    for token in _TERM_RE.findall(question.lower()):
        forms = {token}
        if token.endswith("es") and len(token) > 4:
            forms.add(token[:-2])
        if token.endswith("s") and len(token) > 3:
            forms.add(token[:-1])
        if forms & _GENERIC_HAZARD_TERMS:
            generic = True
        for kind, lexicon in _KIND_TERMS.items():
            if forms & lexicon:
                kinds.add(kind)
    if generic and not kinds:
        kinds.update(_GENERIC_HAZARD_KINDS)
    return frozenset(kinds)


def _kind_filter(kinds: frozenset[str]):
    """SQL predicate selecting the rows belonging to `kinds`."""
    clauses = []
    if "earthquake" in kinds:
        clauses.append(EventRow.source == "usgs-quake")
    if "cyber" in kinds:
        clauses.append(EventRow.source.startswith("abuse-ch-"))
    codes = [_KIND_TO_GDACS_CODE[k] for k in kinds if k in _KIND_TO_GDACS_CODE]
    if codes:
        clauses.append(
            (EventRow.source == "gdacs") & (EventRow.payload["event_type"].astext.in_(codes))
        )
        # EONET carries the same disasters without GDACS's code, so match it on
        # its own title text rather than pretending it shares the taxonomy.
        title_terms = [t for k in kinds for t in _KIND_TERMS.get(k, ())]
        if title_terms:
            eonet = [EventRow.payload["title"].astext.ilike(f"%{term}%") for term in title_terms]
            clauses.append((EventRow.source == "eonet") & or_(*eonet))
    if not clauses:
        return None
    return or_(*clauses)


def _row_country(row: EventRow) -> str | None:
    """Country of a reading, from the column or failing that its place text.

    USGS files "58 km WSW of Puerto Madero, Mexico" with no country column, so
    comparing the column alone left such rows matching anything: the Peru
    reading paired with an unrelated country-less M5.5 and the real Peru pair
    never met (#513).
    """
    if row.country:
        return row.country
    payload = row.payload if isinstance(row.payload, dict) else {}
    text = payload.get("place") or payload.get("eventname") or payload.get("title")
    return country_from_text(str(text)) if text else None


def _row_magnitude(row: EventRow) -> float | None:
    payload = row.payload if isinstance(row.payload, dict) else {}
    magnitude = payload.get("magnitude")
    if magnitude is None:
        return row.severity
    try:
        return float(magnitude)
    except (TypeError, ValueError):
        return row.severity


def _magnitude_key():
    """Ordering key for "biggest first".

    `severity` cannot carry this alone: for USGS it is not monotonic in
    magnitude — live data holds an M7.3 at 0.5, an M5.5 also at 0.5 and an M6.0
    at 0.25, so sorting by it ranked a 5.5 above a 7.3. Richter magnitude is
    divided by ten to land on the same 0..1 scale as severity, which is what
    makes a mixed-hazard question orderable at all; rows without a magnitude
    (GDACS, EONET, cyber) fall back to severity.
    """
    magnitude = cast(EventRow.payload["magnitude"].astext, Float)
    return func.coalesce(magnitude / 10.0, EventRow.severity)


def _kind_of(row: EventRow) -> str:
    source = (row.source or "").lower()
    if source == "usgs-quake":
        return "earthquake"
    if source.startswith("abuse-ch-"):
        return "cyber"
    payload = row.payload if isinstance(row.payload, dict) else {}
    if source == "gdacs":
        return _GDACS_CODE_TO_KIND.get(str(payload.get("event_type") or ""), "hazard")
    if source == "eonet":
        title = str(payload.get("title") or "").lower()
        for kind, lexicon in _KIND_TERMS.items():
            if any(term in title for term in lexicon):
                return kind
    return "hazard"


def _where(row: EventRow) -> str:
    """Human-readable location. Never a bare ISO code: handed "PG" the model
    wrote "PG (likely Papua New Guinea)", guessing at data it was given."""
    payload = row.payload if isinstance(row.payload, dict) else {}
    place = payload.get("place") or payload.get("eventname") or payload.get("title")
    if place:
        return str(place)
    return country_name(row.country) or "location not reported"


def _aware(moment: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; Postgres returns aware values."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _headline(row: EventRow, kind: str) -> str:
    """A short factual line. Instrument readings, not prose."""
    payload = row.payload if isinstance(row.payload, dict) else {}
    if kind == "earthquake" and payload.get("magnitude") is not None:
        return f"Magnitude {payload['magnitude']} earthquake — {_where(row)}"
    if kind == "cyber":
        threat = payload.get("threat") or "malicious host"
        return f"Cyber: {str(threat).replace('_', ' ')} — {payload.get('url') or ''}".strip()
    return f"{kind.capitalize()} — {_where(row)}"


def _deduplicated(rows: list[EventRow]) -> list[EventRow]:
    """Collapse one physical event reported by several feeds.

    USGS and GDACS both publish major earthquakes, so the same shock arrives
    twice — live data showed an M7.3 off Puerto Madero listed by both. Left
    alone the model reads two rows as two earthquakes and says so.

    Only rows from *different* sources are merged. Two readings of the same
    magnitude from the same feed are an aftershock sequence, not a duplicate,
    and collapsing those would erase real seismic activity — live data holds
    eight distinct M5.3 quakes from USGS alone.

    Deliberately not time-bounded. The obvious rule — same magnitude within a
    couple of hours — does not work: USGS timestamps a quake's origin while
    GDACS timestamps its own report, and the shared M7.3 above sits two days
    apart between the two feeds. Any window wide enough to catch that would
    also swallow genuinely distinct events.

    Country must agree when both rows carry one. Magnitude alone is not enough:
    a window holding several M5.5 readings paired them across continents, so
    the genuine Peru pair never matched each other and the block listed Peru
    twice (#513).

    The residual risk is two different quakes of identical magnitude, to one
    decimal, in the same country, from two feeds, inside the same window. That
    is rare enough to accept against the double-reporting this prevents.
    """
    kept: list[EventRow] = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        magnitude = payload.get("magnitude")
        if magnitude is None:
            kept.append(row)
            continue
        match = None
        for other in kept:
            other_payload = other.payload if isinstance(other.payload, dict) else {}
            other_magnitude = other_payload.get("magnitude")
            if other_magnitude is None or other.source == row.source:
                continue
            if _kind_of(other) != _kind_of(row):
                continue
            if round(float(other_magnitude), 1) != round(float(magnitude), 1):
                continue
            # Same magnitude in two different countries is two earthquakes.
            # Without this, a pool holding several M5.5s paired them across
            # continents: the Peru pair mismatched against unrelated readings
            # and both survived, so the block listed Peru twice (#513).
            if _row_country(other) != _row_country(row):
                continue
            match = other
            break
        if match is None:
            kept.append(row)
            continue
        # Same event, two feeds: keep whichever names the place.
        match_place = str((match.payload or {}).get("place") or "")
        if len(str(payload.get("place") or "")) > len(match_place):
            kept[kept.index(match)] = row
    return kept


#: Magnitude gap still treated as the same event. Initial reports get revised —
#: the Peru quake in #513 was carried as 5.1 by newsrooms and 5.5 by USGS — so a
#: question quoting one number must still reach the reading holding the other.
_MAGNITUDE_TOLERANCE = 0.6

_NUMBER_RE = re.compile(r"\b(\d(?:\.\d)?)\b")


def question_magnitudes(question: str | None) -> list[float]:
    """Magnitudes a question quotes. Richter only ever reads 0-9.9 here, so a
    bare number in a hazard question is a magnitude and not a count."""
    if not question:
        return []
    return [float(m.group(1)) for m in _NUMBER_RE.finditer(question)]


def _match_reason(row: EventRow, iso: str | None, magnitudes: list[float]) -> str | None:
    """Why this reading answers the question, or None if it merely exists.

    Place is checked against both the row's country and its free-text place:
    USGS files "2 km WSW of Sicaya, Peru" with no country at all, so matching
    on the column alone would miss the very reading the question asks for.
    """
    payload = row.payload if isinstance(row.payload, dict) else {}
    if iso:
        name = (country_name(iso) or "").lower()
        place = str(payload.get("place") or payload.get("eventname") or "").lower()
        if row.country == iso or (name and name in place):
            return "place"
    magnitude = payload.get("magnitude")
    if magnitude is not None and magnitudes:
        try:
            value = float(magnitude)
        except (TypeError, ValueError):
            return None
        if any(abs(value - asked) <= _MAGNITUDE_TOLERANCE for asked in magnitudes):
            return "magnitude"
    return None


def build_qa_sensors(
    session: Session,
    *,
    question: str | None = None,
    now: datetime | None = None,
    start_n: int = 1,
    limit: int = SENSOR_LIMIT,
) -> list[dict[str, Any]]:
    """Sensor readings relevant to the question, as numbered sources.

    `start_n` continues the story numbering so the model sees one citable list
    rather than two competing ones.
    """
    kinds = question_kinds(question)
    if not kinds:
        return []
    predicate = _kind_filter(kinds)
    if predicate is None:
        return []

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=SENSOR_WINDOW_H)
    rows = (
        session.execute(
            select(EventRow)
            .where(EventRow.occurred_at >= cutoff, predicate)
            # "Big earthquakes" wants the largest, not the newest.
            .order_by(_magnitude_key().desc().nullslast(), EventRow.occurred_at.desc())
            # Over-fetch well past the cap: cross-feed duplicates are collapsed
            # below, and a reading matching the question's place can sit far
            # down the magnitude ranking — the Peru quake in #513 was tenth.
            .limit(limit * 25)
        )
        .scalars()
        .all()
    )

    # Rank by whether the reading answers THIS question, then by size. Selecting
    # purely by magnitude returned the six biggest quakes on earth for a
    # question about Peru, and the model cited a New Zealand reading as
    # confirmation of the Peru event (#513).
    iso = country_from_text(question)
    magnitudes = question_magnitudes(question)
    reasons = {id(row): _match_reason(row, iso, magnitudes) for row in rows}
    ranked = sorted(
        _deduplicated(rows),
        key=lambda row: (
            0 if reasons.get(id(row)) == "place" else 1 if reasons.get(id(row)) else 2,
            -(_row_magnitude(row) or 0.0),
        ),
    )

    out: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        kind = _kind_of(row)
        out.append(
            {
                "n": start_n + len(out),
                "kind": kind,
                "source": row.source,
                "headline": _headline(row, kind),
                #: Why this reading is here. The model must be able to tell a
                #: reading that answers the question from one included only to
                #: fill the block, or it cites the filler as confirmation (#513).
                "match": reasons.get(id(row)) or "largest",
                #: Hours, matching the story "age" field the prompt already
                #: teaches the model to read. An ISO timestamp costs three
                #: times the tokens and gets misread as a date to convert.
                "age_hours": round((now - _aware(row.occurred_at)).total_seconds() / 3600, 1),
                #: `severity` is deliberately absent. It is an internal 0..1
                #: score, and handed it the model wrote "with a severity of
                #: 0.2" into the answer — an invented-looking number the reader
                #: cannot interpret. Magnitude already carries the size (#507).
            }
        )
    return out


def build_sensor_summary(
    session: Session,
    *,
    question: str | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-kind counts across the whole window, so the answer can quote totals
    the capped event list does not show."""
    kinds = question_kinds(question)
    if not kinds:
        return {}
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=SENSOR_WINDOW_H)

    summary: dict[str, dict[str, Any]] = {}
    for kind in sorted(kinds):
        predicate = _kind_filter(frozenset({kind}))
        if predicate is None:
            continue
        count, peak = session.execute(
            select(func.count(EventRow.id), func.max(EventRow.severity)).where(
                EventRow.occurred_at >= cutoff, predicate
            )
        ).one()
        if count:
            summary[kind] = {"count": count, "window_hours": SENSOR_WINDOW_H, "peak_severity": peak}
    return summary
