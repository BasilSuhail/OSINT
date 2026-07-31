"""Which country is this story *about*? (#717)

``app.enrichment.city`` answers "which city is named in this text", and the
map was asking it "which country is this story about". Those diverge on
most foreign-desk journalism: three unrelated stories stacked on the same
London coordinate because each said the word once, while 73% of news rows
carried no country at all because they named no gazetteer city.

This module scores country evidence instead of taking the first city hit:

1. Country names, demonyms and abbreviations, then subnational regions,
   weighted by whether they appear in the title or the summary, with a
   bonus when a country term is anchored at the very start of the
   headline — not merely mentioned early in it. A headline that opens
   with a *list* of countries ("France, Spain and Greece battle
   wildfires") names no single subject, so the bonus is withheld rather
   than handed to whichever one happens to come first. A winner must
   beat the runner-up by ``MARGIN`` or the story is declared ambiguous
   and left countryless.
2. Only if nothing scored does the city gazetteer get a say.
3. Only if that also misses does the feed's own country desk apply.

Absence is a real answer. Roughly 40% of headlines ("box office", "gold
prices rise") have no geography, and inventing one for them is the bug,
not the fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.enrichment.city import city_for
from app.enrichment.geo_terms import (
    TermClass,
    country_at,
    find_isos,
    leading_iso,
    normalise_keeping,
)

#: Bumped with any change to weights, margin, or layer order. Stamped into
#: payload.enrichment_meta so a re-run can be told apart from an old row.
GEO_METHOD_VERSION: str = "geo.terms.v1.0"

#: Score per term class when the match is in the title.
TITLE_WEIGHTS: dict[TermClass, float] = {"name": 3.0, "abbrev": 3.0, "region": 2.0}

#: Same, for the summary. A headline is the story's claim about itself.
SUMMARY_WEIGHTS: dict[TermClass, float] = {"name": 1.0, "abbrev": 1.0, "region": 0.5}

#: Added when a country's term is anchored at the very start of the
#: headline (``geo_terms.leading_iso``, not merely "appears early").
#: "Israel slams Canada" is about Israel; both are named, only Israel
#: opens it. Withheld when the opening is a coordinated list of
#: countries — see ``_opens_with_coordinated_countries`` — because then
#: none of them is singularly the subject either.
LEAD_BONUS: float = 1.0

#: How far the winner must clear the runner-up. Below this the story names
#: more countries than it is about, and we say so instead of guessing.
MARGIN: float = 1.0


@dataclass(frozen=True)
class GeoVerdict:
    """Where a news story is, and how we decided."""

    #: ISO 3166-1 alpha-2, or None when the story has no resolvable country.
    iso: str | None
    #: One of "term", "city", "desk", "ambiguous", "none".
    basis: str
    #: Matched city name, when one was found and agrees with ``iso``.
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    #: Second-place ISO when scoring ran. Kept for the audit trail.
    runner_up: str | None = None


#: Phrases that chain one leading country into a list with the next
#: ("France, Spain and Greece", "Britain as well as France"), rather than
#: naming it as the sole subject. Tried longest-first so "as well as"
#: is not mistaken for a bare "as" (not itself a separator).
_COORD_PHRASES: tuple[str, ...] = ("as well as", "and", "&")


def _consume_coordinator(haystack: str, pos: int) -> int | None:
    """If a coordinating separator begins at ``pos`` — a comma glued to
    the previous word, and/or one of ``_COORD_PHRASES`` — return the
    offset just past it (and any trailing whitespace). Otherwise None.

    ``haystack`` must come from ``normalise_keeping(text, keep=",&")`` so
    a literal comma survives normalisation instead of collapsing to an
    indistinguishable space.
    """
    saw_comma = False
    if pos < len(haystack) and haystack[pos] == ",":
        saw_comma = True
        pos += 1
    while pos < len(haystack) and haystack[pos] == " ":
        pos += 1
    for phrase in _COORD_PHRASES:
        end = pos + len(phrase)
        if haystack[pos:end].lower() == phrase and (end == len(haystack) or haystack[end] in " ,"):
            end_ws = end
            while end_ws < len(haystack) and haystack[end_ws] == " ":
                end_ws += 1
            return end_ws
    return pos if saw_comma else None


def _opens_with_coordinated_countries(title: str) -> bool:
    """True when the title opens with 2+ country terms chained only by
    ',', 'and', '&', or 'as well as' — "France, Spain and Greece battle
    wildfires" — so no single one of them is the headline's subject.

    Walks anchored country matches from the start using ``country_at``
    (the same longest-first, multi-word-aware matcher ``leading_iso``
    uses), alternating a match with a coordinating separator, and stops
    the instant either is missing. Using a *different*, weaker matcher
    here — e.g. testing one raw token at a time — is exactly the bug
    this replaced: "South Korea, Japan and China" was walked one word at
    a time, "South" alone matched no country, and the walk gave up
    before it ever saw "South Korea" as a whole (#717 whole-branch
    review, Important 1). "Iraq demands evidence..." still stops after
    one match ("demands" is not a separator) and is not coordinated.
    """
    haystack = normalise_keeping(title, ",&")
    matched = 0
    pos = 0
    while True:
        hit = country_at(haystack, pos)
        if hit is None:
            break
        _, end = hit
        matched += 1
        pos = end
        next_pos = _consume_coordinator(haystack, pos)
        if next_pos is None:
            break
        pos = next_pos
    return matched >= 2


def _score(title: str, summary: str) -> dict[str, float]:
    """Weighted evidence per ISO across title and summary."""
    scores: dict[str, float] = {}

    for iso, classes in find_isos(title).items():
        scores[iso] = scores.get(iso, 0.0) + max(TITLE_WEIGHTS[c] for c in classes)

    for iso, classes in find_isos(summary).items():
        scores[iso] = scores.get(iso, 0.0) + max(SUMMARY_WEIGHTS[c] for c in classes)

    lead = leading_iso(title)
    if lead is not None and lead in scores and not _opens_with_coordinated_countries(title):
        scores[lead] += LEAD_BONUS

    return scores


@lru_cache(maxsize=8192)
def resolve_geo(
    title: str,
    summary: str = "",
    *,
    desk_country: str | None = None,
    city_hint: str | None = None,
) -> GeoVerdict:
    """Resolve one news story to a country, or honestly to nothing.

    ``desk_country`` is the country a feed's section is *about* (BBC UK →
    GB), not the outlet's home country. It applies only when the text
    yields nothing at all — a national paper republishing world news must
    not have every foreign story stamped with its own flag (#166).

    ``city_hint`` biases the city gazetteer on name collisions
    (Cambridge UK over Cambridge MA), exactly as before.
    """
    title = title or ""
    summary = summary or ""

    scores = _score(title, summary)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))

    winner: str | None = None
    runner_up: str | None = ranked[1][0] if len(ranked) > 1 else None

    if ranked:
        top_iso, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_score - second_score >= MARGIN:
            winner = top_iso
        elif len(ranked) > 1:
            # Two or more countries scored and neither cleared the gate:
            # the story names more countries than it is about. Say
            # nothing rather than pick one — this is the precision half
            # of #717.
            #
            # A *lone* sub-margin candidate is a different situation and
            # must not take this branch: one region mentioned only in
            # the summary (score 0.5) has no runner-up to be ambiguous
            # against — it is weak evidence, not a contradiction. Leave
            # ``winner`` unset and fall through below to the city layer
            # and then the desk prior, exactly as if nothing had scored
            # at all (#717 whole-branch review, Important 2).
            return GeoVerdict(iso=None, basis="ambiguous", runner_up=runner_up)

    city = (
        city_for(f"{title} {summary}".strip(), country_hint=city_hint)
        if (title or summary)
        else None
    )

    if winner is not None:
        # Coordinates only when the city agrees. A London pin on a story
        # about China is the bug, not a nice-to-have.
        if city is not None and city.iso == winner:
            return GeoVerdict(
                iso=winner,
                basis="term",
                city=city.name,
                lat=city.lat,
                lon=city.lon,
                runner_up=runner_up,
            )
        return GeoVerdict(iso=winner, basis="term", runner_up=runner_up)

    if city is not None:
        return GeoVerdict(iso=city.iso, basis="city", city=city.name, lat=city.lat, lon=city.lon)

    if desk_country:
        return GeoVerdict(iso=desk_country.upper(), basis="desk")

    return GeoVerdict(iso=None, basis="none")


def resolved_news_scope(
    iso: str | None,
    lat: float | None,
    lon: float | None,
    default_country: str | None,
) -> str:
    """The three-value scope MapPane's clustering reads off a stored row.

    Despite the name, this is not an editorial judgement about scope — it
    is the rendering signal from #166 that decides whether a coordless
    row is allowed to fall back to a country centroid. ``osint-frontend``
    only skips that fallback when ``scope != "local"``, so ``"local"`` is
    a promise that real coordinates exist; it is never re-checked against
    ``lat``/``lon`` on the frontend.

    Before #717, ``local`` was only reachable when a *city* had matched,
    which meant coordinates always came along for free. This resolver can
    now name a country from term evidence alone (country names, demonyms,
    regions) with no city and therefore no coordinates. A coordless
    ``local`` row would slip past MapPane's guard and get pinned on the
    country centroid instead — every such row landing on the same point,
    which is precisely the stacked-pin bug #166 fixed. So ``local``
    requires coordinates, not just a country match: a countried-but-
    coordless row is ``world`` instead, which is what
    ``worldNewsAggregates`` on the frontend is built to carry.

    Do not "fix" this back to pure editorial-scope semantics without
    re-reading #166 and the #717 whole-branch review (Critical 1) — that
    is exactly the regression this function exists to prevent.
    """
    if iso is None:
        return "unknown"
    if lat is not None and lon is not None and (default_country is None or iso == default_country):
        return "local"
    return "world"
