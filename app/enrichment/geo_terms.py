"""Country / region / demonym term index for news geo-resolution (#717).

The city gazetteer answers "which city is named". This module supplies the
vocabulary for the different question the map actually asks: "which country
is this about". A story saying "in Britain" or "German police" names no
city and is invisible to ``app.enrichment.city``; 73% of news rows had no
country for exactly that reason.

Country names themselves come from the Natural Earth admin-0 file already
bundled for ``app.enrichment.country``. ``data/geo_terms.json`` adds only
what Natural Earth lacks: colloquial aliases ("Britain"), demonyms
("German"), case-sensitive abbreviations ("UK", "US"), and subnational
regions ("Wales", "Bavaria", "Tamil Nadu").

Abbreviations are matched **case-sensitively**. Lowercasing them matched
the pronoun in "finds a way to surprise us" as the United States.

Matching walks the index longest-first and blanks out each match's span
before testing shorter terms, so "New South Wales" (Australia) consumes
itself before the bare "Wales" (a GB region) ever gets a chance to fire
inside it. Term text is normalised the same way the input text is —
punctuation collapsed to whitespace — so a punctuated term like "U.K." or
a hyphenated Natural Earth name like "Guinea-Bissau" lines up with the
equally-normalised haystack instead of never matching at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

# ``_names_by_iso`` is private to country.py. Imported rather than
# duplicated: re-parsing the 820 KB admin-0 file a second time to rebuild
# the same dict would be worse. If ruff objects, promote it to a public
# ``names_by_iso()`` there and keep the old name as an alias — do not copy
# the parsing loop.
from app.enrichment.country import _names_by_iso

_DATA_PATH = Path(__file__).parent / "data" / "geo_terms.json"
#: Region → point, built by scripts/build_region_coords.py (#717).
_REGION_POINTS_PATH = Path(__file__).parent / "data" / "region_coords.json"

#: Term classes, in descending weight order. Scoring lives in ``geo.py``.
TermClass = Literal["name", "abbrev", "region"]

#: Shortest a case-insensitive term may be. Below this, terms collide with
#: ordinary English ("Ur", "Ho", "Mali" inside "Somalia" is caught by the
#: word-boundary regex, but three-letter terms are not worth the risk).
_MIN_TERM_LEN: int = 4


@dataclass(frozen=True)
class Term:
    """One searchable phrase and the country it implies."""

    text: str
    iso: str
    term_class: TermClass
    case_sensitive: bool


def _load_extra() -> dict[str, dict[str, list[str]]]:
    with _DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _build_terms() -> list[Term]:
    terms: list[Term] = []
    seen: set[tuple[str, bool]] = set()

    def add(text: str, iso: str, term_class: TermClass, *, case_sensitive: bool) -> None:
        cleaned = text.strip() if case_sensitive else text.strip().lower()
        if not cleaned:
            return
        if not case_sensitive and len(cleaned) < _MIN_TERM_LEN:
            return
        key = (cleaned, case_sensitive)
        if key in seen:
            # First writer wins, so a name never gets downgraded to a region.
            return
        seen.add(key)
        terms.append(
            Term(text=cleaned, iso=iso, term_class=term_class, case_sensitive=case_sensitive)
        )

    # Natural Earth country names first: they are the highest-confidence
    # terms and must not be shadowed by a region alias from the JSON.
    for iso, name in _names_by_iso().items():
        add(name, iso, "name", case_sensitive=False)

    for iso, groups in _load_extra().items():
        for alias in groups.get("aliases", []):
            add(alias, iso, "name", case_sensitive=False)
        for demonym in groups.get("demonyms", []):
            add(demonym, iso, "name", case_sensitive=False)
        for abbrev in groups.get("abbrevs", []):
            add(abbrev, iso, "abbrev", case_sensitive=True)
        for region in groups.get("regions", []):
            add(region, iso, "region", case_sensitive=False)

    # Longest first so "South Korea" is consumed before "Korea", and
    # "New South Wales" before "Wales".
    terms.sort(key=lambda t: len(t.text), reverse=True)
    return terms


@lru_cache(maxsize=1)
def term_index() -> tuple[Term, ...]:
    """Every term, longest-first. Built once per process."""
    return tuple(_build_terms())


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[re.Pattern[str], Term], ...]:
    """Word-boundary patterns, parallel to ``term_index()``.

    Word boundaries are what stop "Oman" matching inside "Romania" and
    "Chad" inside "Chadwick". The term text is run through the same
    ``_normalise`` used on the haystack, so a punctuated term ("U.K.") or
    a hyphenated one ("Guinea-Bissau") is compiled against the same
    collapsed-whitespace form it will be searched for in, rather than
    against its original punctuation that the haystack no longer has.
    """
    out: list[tuple[re.Pattern[str], Term]] = []
    for term in term_index():
        flags = 0 if term.case_sensitive else re.IGNORECASE
        pattern_text = _normalise(term.text)
        out.append((re.compile(rf"\b{re.escape(pattern_text)}\b", flags), term))
    return tuple(out)


def _normalise(text: str, *, keep: str = "") -> str:
    """Collapse punctuation to whitespace and whitespace runs to one space.

    Applied to both the input text and each term's text before compiling,
    so "Spain's" still hits "spain" and "U.K." (normalised to "U K")
    lines up with "U.K. forces" (normalised to "U K forces").

    ``keep`` names characters to leave untouched instead of collapsing to
    whitespace. No term ever contains a comma or '&', so keeping them in
    a caller's haystack cannot change what matches — it only preserves
    information the caller wants (see ``normalise_keeping``).
    """
    pattern = r"[^\w\s" + re.escape(keep) + r"]"
    collapsed = re.sub(pattern, " ", text)
    return re.sub(r"\s+", " ", collapsed).strip()


def normalise_keeping(text: str, keep: str) -> str:
    """Public wrapper for callers building their own haystack to feed
    ``country_at`` — e.g. ``app.enrichment.geo``'s coordinated-list
    detector, which needs commas to survive normalisation so it can tell
    a separator from an ordinary word gap."""
    return _normalise(text, keep=keep)


def country_at(haystack: str, pos: int = 0) -> tuple[str, int] | None:
    """ISO and end-offset of the longest country term anchored exactly at
    offset ``pos`` in an already-normalised ``haystack``, or ``None``.

    The shared core behind ``leading_iso`` (``pos=0``) and
    ``app.enrichment.geo``'s coordinated-list detector, so a multi-word
    name like "South Korea" is recognised identically by both instead of
    one matcher anchoring whole names and the other testing single
    tokens — see #717 whole-branch review, Important 1.
    """
    for pattern, term in _compiled():
        m = pattern.match(haystack, pos)
        if m:
            return term.iso, m.end()
    return None


def _blank(match: re.Match[str]) -> str:
    """Replace a matched span with same-length non-word placeholders.

    Keeps every other term's offsets stable while making the consumed
    span unable to satisfy a shorter term's word-boundary check, so
    "Wales" cannot re-match text already claimed by "New South Wales".
    """
    return "\0" * (match.end() - match.start())


@lru_cache(maxsize=8192)
def _find_isos_cached(text: str) -> dict[str, frozenset[TermClass]]:
    """Cached core of ``find_isos``. See that function for behaviour.

    Returns the same dict object on every call with matching ``text`` —
    callers must go through the public ``find_isos`` wrapper, which hands
    back a fresh copy so the cached mapping can never be mutated.
    """
    if not text or not text.strip():
        return {}
    haystack = _normalise(text)
    found: dict[str, set[TermClass]] = {}
    # Longest-first order (inherited from term_index()/_compiled()) plus
    # blanking each match means a longer term consumes its span before any
    # shorter term gets to test it — "new south wales" is gone before
    # "wales" ever looks at that stretch of text.
    for pattern, term in _compiled():
        haystack, hits = pattern.subn(_blank, haystack)
        if hits:
            found.setdefault(term.iso, set()).add(term.term_class)
    return {iso: frozenset(classes) for iso, classes in found.items()}


@lru_cache(maxsize=1)
def _region_points() -> dict[str, dict[str, tuple[float, float]]]:
    """ISO2 → normalised region name → (lat, lon).

    Built by ``scripts/build_region_coords.py`` from Natural Earth's
    admin-1 label anchors. Absent or unreadable, regions simply carry no
    point and the resolver behaves as it did before (#717).
    """
    try:
        with _REGION_POINTS_PATH.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {
        iso: {name: (float(p[0]), float(p[1])) for name, p in regions.items()}
        for iso, regions in raw.items()
    }


@lru_cache(maxsize=8192)
def region_point_for(text: str, iso: str) -> tuple[float, float] | None:
    """Coordinates of the largest sub-national place of ``iso`` named in ``text``.

    Longest-first, so "north yorkshire" is preferred over "yorkshire"
    when both appear. Returns None when the text names no such place, or
    when it has no point in the bundled table (20 of 276 do not — they
    keep a country and no pin, as before).

    The point table decides what may be pinned, not the term's scoring
    class. Gaza and the West Bank are classed as *names* of Palestine, so
    a story about either resolves to PS at full name weight — but they are
    territories, not the country, and small enough to be real places, so
    they carry a point too (#737). Tying the pin to the class instead
    would force a choice between weighing them correctly and drawing them
    at all. ``build_region_coords`` is what refuses a point to anything
    country-sized.
    """
    regions = _region_points().get(iso.upper()) if iso else None
    if not regions or not text:
        return None
    haystack = _normalise(text)
    for pattern, term in _compiled():
        if term.iso != iso.upper():
            continue
        if pattern.search(haystack):
            point = regions.get(term.text)
            if point is not None:
                return point
    return None


def find_isos(text: str) -> dict[str, frozenset[TermClass]]:
    """ISO alpha-2 → the set of term classes that matched in ``text``.

    Case is preserved for the abbreviation patterns; the lowercase ones
    carry ``re.IGNORECASE`` themselves. Returns an empty dict for empty or
    whitespace-only input. The returned dict is a fresh shallow copy each
    call — its ``frozenset`` values are shared and immutable, but the
    outer dict itself is safe for a caller to mutate without corrupting
    the ``lru_cache``d result backing it.
    """
    return dict(_find_isos_cached(text))


@lru_cache(maxsize=8192)
def leading_iso(text: str) -> str | None:
    """ISO whose term begins at the very start of ``text``, or ``None``.

    Anchored: ``re.match``, not ``re.search``. "As Iran and Ukraine wars
    converge" does not lead with Iran just because it is the second
    word — ``iran`` begins at an offset greater than zero, so nothing
    here matches and the caller gets ``None``. Patterns are walked
    longest-first (the same order ``find_isos`` uses), so a multi-word
    name is tried whole before any shorter term inside it — "South
    Korea slams Japan" resolves to ``KR`` rather than never matching
    because only a single token was checked.

    Used by ``app.enrichment.geo`` to decide which, if any, country a
    headline's *subject* names — a question "does this appear early"
    cannot answer, only "does this open the text" can.
    """
    if not text or not text.strip():
        return None
    haystack = _normalise(text)
    hit = country_at(haystack, 0)
    return hit[0] if hit else None
