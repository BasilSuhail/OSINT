"""Strict named-place resolution for RSS news (#745, child of #717).

The ingest-time resolver can truthfully place a story at a city or region.
This module is the slower second pass: it upgrades an explicit venue, building,
street, or site to its own coordinate when Wikidata proves the identity.

The gate is deliberately narrow. A result must match the extracted name, carry
coordinates, and agree with the story country. When city context exists, it
must also name that city in its description and sit nearby. Search rank never
decides identity. Unknown and ambiguous places do not move the marker.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db_models import EventRow, PlaceLookupRow
from app.models import Category, Event

PLACE_METHOD_VERSION: Final[str] = "place.wikidata.v1.4"
# English candidate identity is unchanged and keeps its v1.1 cache material.
# Local-language candidate identity is also unchanged: v1.3 keys include their
# bounded language list. v1.4 is a pre-lookup refusal rule, not a cache-key bump.
PLACE_LOOKUP_KEY_VERSION: Final[str] = "place.wikidata.v1.3"
ENGLISH_LOOKUP_KEY_VERSION: Final[str] = "place.wikidata.v1.1"
WIKIDATA_API_URL: Final[str] = "https://www.wikidata.org/w/api.php"
WIKIDATA_USER_AGENT: Final[str] = (
    "OSINT-ground-truth/1.0 "
    "(https://github.com/BasilSuhail/OSINT; BasilSuhail@users.noreply.github.com)"
)
MAX_LOCALITY_DISTANCE_KM: Final[float] = 75.0
NEGATIVE_CACHE_TTL: Final[timedelta] = timedelta(days=30)
SEARCH_LIMIT: Final[int] = 10
MAX_SEARCH_LANGUAGES: Final[int] = 3
WIKIDATA_MAXLAG: Final[int] = 15
PLACE_SCAN_LIMIT: Final[int] = 2000

PlacePrecision = Literal["building", "street", "site"]
LookupStatus = Literal["resolved", "no_match", "ambiguous"]
TermPosition = Literal["prefix", "suffix", "both"]

_STREET_SUFFIXES: Final[frozenset[str]] = frozenset(
    {"avenue", "boulevard", "drive", "lane", "road", "square", "street"}
)
_SITE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {"gardens", "harbour", "harbor", "marina", "park", "plaza", "port"}
)
_BUILDING_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "airport",
        "arena",
        "barracks",
        "base",
        "bridge",
        "building",
        "castle",
        "cathedral",
        "center",
        "centre",
        "church",
        "cinema",
        "college",
        "consulate",
        "court",
        "courthouse",
        "dam",
        "embassy",
        "factory",
        "gallery",
        "hall",
        "hospital",
        "hotel",
        "jail",
        "library",
        "mall",
        "market",
        "mine",
        "mosque",
        "museum",
        "palace",
        "parliament",
        "plant",
        "prison",
        "refinery",
        "school",
        "stadium",
        "station",
        "synagogue",
        "temple",
        "terminal",
        "theater",
        "theatre",
        "tower",
        "university",
    }
)
_PLACE_SUFFIXES: Final[frozenset[str]] = _STREET_SUFFIXES | _SITE_SUFFIXES | _BUILDING_SUFFIXES

# These phrases name an institutional class, not one identifiable place.  A
# search engine is free to return any member of that class, which is exactly
# how "Magistrates' Court" in Liverpool became Garston Reading Room (#755).
# Keep this list narrow: modifiers such as "Karnataka" and possessive names
# such as "King's" are real identity evidence and must remain candidates.
GENERIC_PLACE_REASON: Final[str] = "generic_institution_class"
_GENERIC_PLACE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "central station",
        "city hall",
        "county jail",
        "crown court",
        "general hospital",
        "high court",
        "magistrates court",
    }
)
_GENERIC_CACHE_QUERY_TEXTS: Final[frozenset[str]] = frozenset(
    {
        *_GENERIC_PLACE_NAMES,
        *_PLACE_SUFFIXES,
        "magistrates' court",
        "magistrates\u2019 court",
    }
)

# A named place ends in a place-kind word and starts with capitalised words.
# Lowercase joiners are allowed inside names ("Bank of England Museum"), but
# ordinary sentence words stop the match ("fire at King's Theatre").
_CURLY_APOSTROPHE: Final[str] = "\N{RIGHT SINGLE QUOTATION MARK}"
_NAME_TOKEN = rf"(?:[A-ZÀ-ÖØ-Þ][\w'{_CURLY_APOSTROPHE}.-]*|[A-Z]{{2,}}|of|the|and|de|la|al|&|St\.?)"
_CANDIDATE_RE = re.compile(
    rf"(?<![\w'{_CURLY_APOSTROPHE}])({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,6}}?\s+"
    rf"(?i:{'|'.join(sorted(_PLACE_SUFFIXES, key=len, reverse=True))}))\b",
)

# These are physical-place kind words, not a general language detector. A
# candidate is assigned only the bounded Wikidata languages implied by the
# kind word that made it extractable. Shared spellings intentionally carry at
# most two languages; the resolver never fans out across this whole table.
_MultilingualTerm = tuple[str, PlacePrecision, tuple[str, ...], TermPosition]
_MULTILINGUAL_TERMS: Final[tuple[_MultilingualTerm, ...]] = (
    # French — accented forms are useful evidence that English-only matching
    # currently drops, while unaccented shared words remain deliberately out.
    ("aéroport", "building", ("fr",), "prefix"),
    ("hôpital", "building", ("fr",), "prefix"),
    ("université", "building", ("fr",), "prefix"),
    ("cathédrale", "building", ("fr",), "prefix"),
    ("église", "building", ("fr",), "prefix"),
    ("musée", "building", ("fr",), "prefix"),
    ("théâtre", "building", ("fr",), "prefix"),
    ("gare", "building", ("fr",), "prefix"),
    ("rue", "street", ("fr",), "prefix"),
    # Spanish / Portuguese shared forms stay bounded to two searches.
    ("aeropuerto", "building", ("es",), "prefix"),
    ("aeroporto", "building", ("pt",), "prefix"),
    ("universidad", "building", ("es",), "prefix"),
    ("universidade", "building", ("pt",), "prefix"),
    ("estadio", "building", ("es",), "prefix"),
    ("estádio", "building", ("pt",), "prefix"),
    ("estación", "building", ("es",), "prefix"),
    ("estação", "building", ("pt",), "prefix"),
    ("cárcel", "building", ("es",), "prefix"),
    ("prisão", "building", ("pt",), "prefix"),
    ("calle", "street", ("es",), "prefix"),
    ("rua", "street", ("pt",), "prefix"),
    ("avenida", "street", ("es", "pt"), "prefix"),
    # German kind words may precede or follow the proper name.
    ("flughafen", "building", ("de",), "both"),
    ("bahnhof", "building", ("de",), "both"),
    ("krankenhaus", "building", ("de",), "both"),
    ("universität", "building", ("de",), "both"),
    ("gefängnis", "building", ("de",), "both"),
    ("brücke", "building", ("de",), "both"),
    ("straße", "street", ("de",), "both"),
    ("strasse", "street", ("de",), "both"),
    # Russian and Ukrainian use distinct local-script searches when the kind
    # word identifies one language; shared forms query both, still bounded.
    ("аэропорт", "building", ("ru",), "both"),
    ("аеропорт", "building", ("uk",), "both"),
    ("больница", "building", ("ru",), "both"),
    ("лікарня", "building", ("uk",), "both"),
    ("университет", "building", ("ru",), "both"),
    ("університет", "building", ("uk",), "both"),
    ("стадион", "building", ("ru",), "both"),
    ("стадіон", "building", ("uk",), "both"),
    ("вокзал", "building", ("ru", "uk"), "both"),
    ("музей", "building", ("ru", "uk"), "both"),
    ("мост", "building", ("ru",), "both"),
    ("міст", "building", ("uk",), "both"),
    ("улица", "street", ("ru",), "both"),
    ("вулиця", "street", ("uk",), "both"),
    ("площадь", "site", ("ru",), "both"),
    ("площа", "site", ("uk",), "both"),
    # Arabic and Devanagari have no case distinction, so extraction also uses
    # short language-specific stopword lists below.
    ("مطار", "building", ("ar",), "prefix"),
    ("مستشفى", "building", ("ar",), "prefix"),
    ("جامعة", "building", ("ar",), "prefix"),
    ("ملعب", "building", ("ar",), "prefix"),
    ("محطة", "building", ("ar",), "prefix"),
    ("متحف", "building", ("ar",), "prefix"),
    ("مسجد", "building", ("ar",), "prefix"),
    ("كنيسة", "building", ("ar",), "prefix"),
    ("جسر", "building", ("ar",), "prefix"),
    ("شارع", "street", ("ar",), "prefix"),
    ("ميناء", "site", ("ar",), "prefix"),
    ("ساحة", "site", ("ar",), "prefix"),
    ("हवाई अड्डा", "building", ("hi",), "suffix"),
    ("अस्पताल", "building", ("hi",), "both"),
    ("विश्वविद्यालय", "building", ("hi",), "both"),
    ("स्टेडियम", "building", ("hi",), "both"),
    ("संग्रहालय", "building", ("hi",), "both"),
    ("स्टेशन", "building", ("hi",), "both"),
    ("पुल", "building", ("hi",), "both"),
    ("सड़क", "street", ("hi",), "both"),
)
_NO_CASE_LANGUAGES: Final[frozenset[str]] = frozenset({"ar", "hi"})
_LANGUAGE_STOPWORDS: Final[dict[str, frozenset[str]]] = {
    "ar": frozenset({"بعد", "ضد", "عبر", "عند", "على", "عن", "في", "من", "نحو", "و", "وسط"}),
    "hi": frozenset({"और", "के", "की", "को", "का", "पर", "में", "से", "बाद", "लिए", "ने"}),
}
_TOKEN_RE = re.compile(r"[^\s,;:!?()\[\]{}<>\"“”]+", re.UNICODE)
_HARD_BOUNDARY_RE = re.compile(r"[,;:!?()\[\]{}<>\n]")
_NAME_JOINERS: Final[frozenset[str]] = frozenset(
    {
        "al",
        "am",
        "an",
        "and",
        "da",
        "das",
        "de",
        "del",
        "der",
        "des",
        "di",
        "do",
        "dos",
        "du",
        "la",
        "le",
        "of",
        "the",
        "von",
        "und",
        "имени",
    }
)


@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    precision: PlacePrecision
    search_languages: tuple[str, ...] = ("en",)

    def __post_init__(self) -> None:
        if not self.search_languages:
            raise ValueError("at least one Wikidata search language is required")
        if len(self.search_languages) > MAX_SEARCH_LANGUAGES:
            raise ValueError("Wikidata search-language fallback exceeds its bound")


@dataclass(frozen=True)
class PlaceCandidateRejection:
    name: str
    reason: str


@dataclass(frozen=True)
class PlaceExtraction:
    candidates: tuple[PlaceCandidate, ...]
    rejections: tuple[PlaceCandidateRejection, ...]


@dataclass(frozen=True)
class PlaceContext:
    country: str
    city: str | None = None
    lat: float | None = None
    lon: float | None = None

    @property
    def has_city_anchor(self) -> bool:
        return self.city is not None and self.lat is not None and self.lon is not None


@dataclass(frozen=True)
class PlaceResolution:
    wikidata_id: str
    label: str
    description: str
    lat: float
    lon: float
    precision: PlacePrecision


@dataclass(frozen=True)
class PlaceVerdict:
    status: LookupStatus
    resolution: PlaceResolution | None = None


def normalise_place_name(text: str) -> str:
    """Comparison form that folds Latin accents without damaging other scripts."""
    folded = unicodedata.normalize("NFKD", text.replace(_CURLY_APOSTROPHE, "'").casefold())
    output: list[str] = []
    previous_base_was_latin = False
    for char in folded:
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            output.append(char)
            previous_base_was_latin = "LATIN" in unicodedata.name(char, "")
        elif category.startswith("M"):
            # NFKD turns é into e + accent. Dropping only Latin marks keeps the
            # established accent-insensitive behaviour while retaining Arabic
            # and Devanagari marks that are part of the written name.
            if not previous_base_was_latin:
                output.append(char)
        else:
            output.append(" ")
            previous_base_was_latin = False
    return " ".join("".join(output).split())


def _precision_for(name: str) -> PlacePrecision:
    suffix = normalise_place_name(name).rsplit(" ", 1)[-1]
    if suffix in _STREET_SUFFIXES:
        return "street"
    if suffix in _SITE_SUFFIXES:
        return "site"
    return "building"


def _clean_candidate(name: str, city: str | None) -> str:
    punctuation = " .,:;!?-\N{EN DASH}\N{EM DASH}"
    cleaned = " ".join(name.strip(punctuation).split())
    cleaned = re.sub(r"^(?:the|and)\s+", "", cleaned, flags=re.IGNORECASE)
    if city:
        city_words = normalise_place_name(city)
        candidate_words = normalise_place_name(cleaned)
        if candidate_words.startswith(f"{city_words} "):
            # "Edinburgh King's Theatre" carries context plus the actual name.
            cleaned = cleaned.split(maxsplit=len(city.split()))[-1]
    return cleaned


@dataclass(frozen=True)
class _TextToken:
    value: str
    literal: str
    normalised: str
    start: int
    end: int


def _text_tokens(text: str) -> list[_TextToken]:
    tokens: list[_TextToken] = []
    trim = ".'\N{RIGHT SINGLE QUOTATION MARK}\N{HORIZONTAL ELLIPSIS}-\N{EN DASH}\N{EM DASH}"
    for match in _TOKEN_RE.finditer(text):
        raw = match.group(0)
        value = raw.strip(trim)
        if not value:
            continue
        left = len(raw) - len(raw.lstrip(trim))
        right = len(raw) - len(raw.rstrip(trim))
        tokens.append(
            _TextToken(
                value=value,
                literal=unicodedata.normalize("NFC", value).casefold(),
                normalised=normalise_place_name(value),
                start=match.start() + left,
                end=match.end() - right,
            )
        )
    return tokens


def _crosses_boundary(text: str, left: _TextToken, right: _TextToken) -> bool:
    return bool(_HARD_BOUNDARY_RE.search(text[left.end : right.start]))


def _first_letter(token: str) -> str:
    return next((char for char in token if char.isalpha()), "")


def _script_matches(token: str, language: str) -> bool:
    script = {"ar": "ARABIC", "hi": "DEVANAGARI"}.get(language)
    first = _first_letter(token)
    return bool(first and script and script in unicodedata.name(first, ""))


def _is_name_token(token: _TextToken, languages: tuple[str, ...], *, have_name: bool) -> bool:
    no_case = next((language for language in languages if language in _NO_CASE_LANGUAGES), None)
    if no_case:
        stopwords = _LANGUAGE_STOPWORDS[no_case]
        return token.normalised not in stopwords and _script_matches(token.value, no_case)
    first = _first_letter(token.value)
    return bool(first and (first.isupper() or (have_name and token.normalised in _NAME_JOINERS)))


def _adjacent_name_indexes(
    text: str,
    tokens: list[_TextToken],
    *,
    start: int,
    step: int,
    languages: tuple[str, ...],
) -> list[int]:
    indexes: list[int] = []
    index = start
    while 0 <= index < len(tokens) and len(indexes) < 6:
        previous = index - step
        if 0 <= previous < len(tokens):
            left, right = sorted((tokens[index], tokens[previous]), key=lambda token: token.start)
            if _crosses_boundary(text, left, right):
                break
        if not _is_name_token(tokens[index], languages, have_name=bool(indexes)):
            break
        indexes.append(index)
        index += step
    if step < 0:
        indexes.reverse()
    # A joiner is valid only inside a name, never at its outside edge.
    while indexes and tokens[indexes[0]].normalised in _NAME_JOINERS:
        indexes.pop(0)
    while indexes and tokens[indexes[-1]].normalised in _NAME_JOINERS:
        indexes.pop()
    return indexes


def _multilingual_candidates(text: str) -> list[PlaceCandidate]:
    tokens = _text_tokens(text)
    candidates: list[PlaceCandidate] = []
    for term, precision, languages, position in _MULTILINGUAL_TERMS:
        # Extraction needs the written kind word itself. Accent folding is for
        # identity comparison, not for deciding that English "theatre" is the
        # French kind word "théâtre" or Portuguese "estadio" is "estádio".
        term_words = unicodedata.normalize("NFC", term).casefold().split()
        width = len(term_words)
        for index in range(len(tokens) - width + 1):
            if [token.literal for token in tokens[index : index + width]] != term_words:
                continue
            term_first = tokens[index]
            term_last = tokens[index + width - 1]
            if position in {"prefix", "both"}:
                names = _adjacent_name_indexes(
                    text,
                    tokens,
                    start=index + width,
                    step=1,
                    languages=languages,
                )
                if names:
                    candidates.append(
                        PlaceCandidate(
                            text[term_first.start : tokens[names[-1]].end],
                            precision,
                            languages,
                        )
                    )
            if position in {"suffix", "both"}:
                names = _adjacent_name_indexes(
                    text,
                    tokens,
                    start=index - 1,
                    step=-1,
                    languages=languages,
                )
                if names:
                    candidates.append(
                        PlaceCandidate(
                            text[tokens[names[0]].start : term_last.end],
                            precision,
                            languages,
                        )
                    )
    return candidates


def _merge_candidate(
    candidates: list[PlaceCandidate],
    positions: dict[str, int],
    candidate: PlaceCandidate,
) -> None:
    key = normalise_place_name(candidate.name)
    if not key or len(key.split()) < 2:
        return
    existing_index = positions.get(key)
    if existing_index is None:
        positions[key] = len(candidates)
        candidates.append(candidate)
        return
    existing = candidates[existing_index]
    languages = tuple(dict.fromkeys((*existing.search_languages, *candidate.search_languages)))
    candidates[existing_index] = PlaceCandidate(
        existing.name,
        existing.precision,
        languages[:MAX_SEARCH_LANGUAGES],
    )


def _generic_place_reason(name: str) -> str | None:
    key = normalise_place_name(name)
    if key in _GENERIC_PLACE_NAMES or key in _PLACE_SUFFIXES:
        return GENERIC_PLACE_REASON
    return None


def _identity_candidate(name: str, city: str | None) -> str:
    """Keep a city modifier when removing it would erase place identity."""
    cleaned = _clean_candidate(name, city)
    unstripped = _clean_candidate(name, None)
    if _generic_place_reason(cleaned) and not _generic_place_reason(unstripped):
        return unstripped
    return cleaned


def extract_place_evidence(payload: dict[str, Any], *, city: str | None = None) -> PlaceExtraction:
    """Extract conservative explicit-place candidates from one RSS payload.

    The deterministic suffix matcher is primary because spaCy is optional in
    production. Existing FAC entities add coverage, but ORG entities are only
    accepted when they also look like a physical place.
    """
    names: list[str] = []
    parts = (str(payload.get("title") or ""), str(payload.get("summary") or ""))
    text = "\n".join(part for part in parts if part)
    for part in parts:
        names.extend(match.group(1) for match in _CANDIDATE_RE.finditer(part))

    entities = payload.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("text") or "").strip()
            label = str(entity.get("label") or "").upper()
            suffix = normalise_place_name(name).rsplit(" ", 1)[-1] if name else ""
            if label == "FAC" or (label == "ORG" and suffix in _PLACE_SUFFIXES):
                names.append(name)

    candidates: list[PlaceCandidate] = []
    positions: dict[str, int] = {}
    rejections: list[PlaceCandidateRejection] = []
    rejected_names: set[str] = set()
    for raw_name in names:
        name = _identity_candidate(raw_name, city)
        key = normalise_place_name(name)
        if not key:
            continue
        reason = _generic_place_reason(name)
        if reason:
            if key not in rejected_names:
                rejected_names.add(key)
                rejections.append(PlaceCandidateRejection(name=name, reason=reason))
            continue
        if len(key.split()) < 2:
            continue
        suffix = key.rsplit(" ", 1)[-1]
        if suffix not in _PLACE_SUFFIXES:
            continue
        _merge_candidate(
            candidates,
            positions,
            PlaceCandidate(name=name, precision=_precision_for(name)),
        )
    for candidate in _multilingual_candidates(text):
        name = _identity_candidate(candidate.name, city)
        key = normalise_place_name(name)
        reason = _generic_place_reason(name)
        if reason:
            if key not in rejected_names:
                rejected_names.add(key)
                rejections.append(PlaceCandidateRejection(name=name, reason=reason))
            continue
        _merge_candidate(
            candidates,
            positions,
            PlaceCandidate(name, candidate.precision, candidate.search_languages),
        )
    return PlaceExtraction(tuple(candidates), tuple(rejections))


def extract_place_candidates(
    payload: dict[str, Any], *, city: str | None = None
) -> tuple[PlaceCandidate, ...]:
    """Return only names specific enough to identify one physical place."""
    return extract_place_evidence(payload, city=city).candidates


def lookup_key(candidate: PlaceCandidate, context: PlaceContext) -> str:
    components = [
        (
            ENGLISH_LOOKUP_KEY_VERSION
            if candidate.search_languages == ("en",)
            else PLACE_LOOKUP_KEY_VERSION
        ),
        normalise_place_name(candidate.name),
        context.country.upper(),
        normalise_place_name(context.city or ""),
    ]
    if candidate.search_languages != ("en",):
        components.append(",".join(candidate.search_languages))
    material = "|".join(components)
    return hashlib.sha256(material.encode()).hexdigest()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _coordinate(entity: dict[str, Any]) -> tuple[float, float] | None:
    claims = entity.get("claims")
    statements = claims.get("P625") if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return None
    ranked = sorted(
        (
            item
            for item in statements
            if isinstance(item, dict) and item.get("rank") != "deprecated"
        ),
        key=lambda item: item.get("rank") != "preferred",
    )
    for statement in ranked:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
            lat, lon = float(value["latitude"]), float(value["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


def _entity_ids(entity: dict[str, Any], property_id: str) -> set[str]:
    claims = entity.get("claims")
    statements = claims.get(property_id) if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return set()
    values: set[str] = set()
    for statement in statements:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
            entity_id = value["id"]
        except (KeyError, TypeError):
            continue
        if isinstance(entity_id, str):
            values.add(entity_id)
    return values


def _string_claims(entity: dict[str, Any], property_id: str) -> set[str]:
    claims = entity.get("claims")
    statements = claims.get(property_id) if isinstance(claims, dict) else None
    if not isinstance(statements, list):
        return set()
    values: set[str] = set()
    for statement in statements:
        try:
            value = statement["mainsnak"]["datavalue"]["value"]
        except (KeyError, TypeError):
            continue
        if isinstance(value, str):
            values.add(value.upper())
    return values


def _response_object(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Wikidata returned a non-object response")
    error = body.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "unknown")
        detail = str(error.get("info") or "Wikidata API error")
        # MediaWiki returns maxlag as HTTP 200. It is a retry signal, never a
        # negative place result; raising keeps it out of the cache.
        raise ValueError(f"Wikidata {code}: {detail}")
    return body


def resolve_wikidata_place(
    candidate: PlaceCandidate,
    context: PlaceContext,
    *,
    client: httpx.Client,
) -> PlaceVerdict:
    """Resolve one candidate without trusting rank or transliteration."""
    expected_name = normalise_place_name(candidate.name)
    exact: dict[str, tuple[dict[str, Any], str]] = {}
    for language in candidate.search_languages:
        search_response = client.get(
            WIKIDATA_API_URL,
            params={
                "action": "wbsearchentities",
                "search": candidate.name,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": SEARCH_LIMIT,
                "format": "json",
                "maxlag": WIKIDATA_MAXLAG,
            },
        )
        body = _response_object(search_response)
        results = body.get("search")
        if not isinstance(results, list):
            raise ValueError("Wikidata search response has no result list")
        for result in results:
            if not isinstance(result, dict):
                continue
            match = result.get("match")
            matched_text = match.get("text") if isinstance(match, dict) else None
            match_language = match.get("language") if isinstance(match, dict) else None
            entity_id = result.get("id")
            is_exact = (
                match_language == language
                and normalise_place_name(str(matched_text or "")) == expected_name
            )
            if isinstance(entity_id, str) and is_exact:
                exact.setdefault(entity_id, (result, language))
    if not exact:
        return PlaceVerdict(status="no_match")

    entity_languages = tuple(dict.fromkeys((*candidate.search_languages, "en")))
    entity_response = client.get(
        WIKIDATA_API_URL,
        params={
            "action": "wbgetentities",
            "ids": "|".join(exact),
            "props": "labels|descriptions|claims",
            "languages": "|".join(entity_languages),
            "format": "json",
            "maxlag": WIKIDATA_MAXLAG,
        },
    )
    entity_body = _response_object(entity_response)
    entities = entity_body.get("entities")
    if not isinstance(entities, dict):
        raise ValueError("Wikidata entity response has no entity object")

    context_city = normalise_place_name(context.city or "")
    potential: list[tuple[str, dict[str, Any], float, float, str, set[str]]] = []
    for entity_id, entity in entities.items():
        if entity_id not in exact or not isinstance(entity, dict):
            continue
        coordinate = _coordinate(entity)
        if coordinate is None:
            continue
        descriptions = entity.get("descriptions")
        description_values = (
            {
                language: str(value.get("value") or "")
                for language, value in descriptions.items()
                if isinstance(language, str) and isinstance(value, dict)
            }
            if isinstance(descriptions, dict)
            else {}
        )
        preferred_languages = (*candidate.search_languages, "en")
        description = next(
            (
                description_values[language]
                for language in preferred_languages
                if description_values.get(language)
            ),
            "",
        )
        lat, lon = coordinate
        if context.has_city_anchor:
            description_forms = (
                f" {normalise_place_name(value)} " for value in description_values.values()
            )
            if not any(f" {context_city} " in words for words in description_forms):
                continue
            assert context.lat is not None and context.lon is not None
            if _haversine_km(context.lat, context.lon, lat, lon) > MAX_LOCALITY_DISTANCE_KM:
                continue
        entity_country_ids = _entity_ids(entity, "P17")
        if not entity_country_ids:
            continue
        potential.append((entity_id, entity, lat, lon, description, entity_country_ids))

    if not potential:
        return PlaceVerdict(status="no_match")

    all_country_ids = sorted({country_id for item in potential for country_id in item[5]})
    country_response = client.get(
        WIKIDATA_API_URL,
        params={
            "action": "wbgetentities",
            "ids": "|".join(all_country_ids),
            "props": "claims",
            "format": "json",
            "maxlag": WIKIDATA_MAXLAG,
        },
    )
    country_body = _response_object(country_response)
    countries = country_body.get("entities")
    if not isinstance(countries, dict):
        raise ValueError("Wikidata country response has no entity object")
    country_iso = {
        country_id: _string_claims(entity, "P297")
        for country_id, entity in countries.items()
        if isinstance(entity, dict)
    }

    matches: list[PlaceResolution] = []
    for entity_id, entity, lat, lon, description, entity_country_ids in potential:
        supported_isos = {
            iso for country_id in entity_country_ids for iso in country_iso.get(country_id, set())
        }
        if context.country.upper() not in supported_isos:
            continue
        search_result, matched_language = exact[entity_id]
        labels = entity.get("labels")
        label_values = (
            {
                language: str(value.get("value") or "")
                for language, value in labels.items()
                if isinstance(language, str) and isinstance(value, dict)
            }
            if isinstance(labels, dict)
            else {}
        )
        label = next(
            (
                label_values[language]
                for language in (matched_language, *candidate.search_languages, "en")
                if label_values.get(language)
            ),
            str(search_result.get("label") or candidate.name),
        )
        matches.append(
            PlaceResolution(
                wikidata_id=entity_id,
                label=label,
                description=description,
                lat=lat,
                lon=lon,
                precision=candidate.precision,
            )
        )

    if len(matches) == 1:
        return PlaceVerdict(status="resolved", resolution=matches[0])
    if len(matches) > 1:
        return PlaceVerdict(status="ambiguous")
    return PlaceVerdict(status="no_match")


_PLACE_PAYLOAD_KEYS: Final[tuple[str, ...]] = (
    "place_name",
    "place_wikidata_id",
    "place_description",
    "place_checked_at",
    "place_model",
    "place_resolution",
    "place_locations",
    "place_candidate_count",
    "place_verified_count",
    "place_rejections",
    "place_rejected_count",
)


def _base_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = dict(payload)
    for key in _PLACE_PAYLOAD_KEYS:
        clean[key] = None
    basis = str(clean.get("geo_basis") or "")
    has_city_point = bool(clean.get("city")) and basis in {"city", "term"}
    clean["geo_precision"] = "city" if has_city_point else ("region" if basis == "region" else None)
    clean["geo_source"] = "natural-earth" if clean["geo_precision"] else None
    return clean


def _rejection_payload(
    payload: dict[str, Any],
    rejections: tuple[PlaceCandidateRejection, ...],
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    clean = _base_payload(payload)
    clean.update(
        {
            "place_checked_at": checked_at.isoformat() if checked_at else None,
            "place_model": PLACE_METHOD_VERSION if checked_at else None,
            "place_resolution": "rejected" if checked_at else None,
            "place_candidate_count": 0,
            "place_verified_count": 0,
            "place_rejections": [
                {"name": rejection.name, "reason": rejection.reason} for rejection in rejections
            ],
            "place_rejected_count": len(rejections),
        }
    )
    return clean


def _with_rejections(
    payload: dict[str, Any], rejections: tuple[PlaceCandidateRejection, ...]
) -> dict[str, Any]:
    #: Last gate before a payload is stored: a `place` basis that cannot name
    #: its location is demoted here rather than becoming a row nobody can
    #: question (#756). No writer produces that state today — a migration left
    #: one behind — so this exists to keep it unrepresentable rather than to
    #: repair a live defect.
    payload = without_unbacked_place(payload)
    if not rejections:
        return payload
    payload["place_rejections"] = [
        {"name": rejection.name, "reason": rejection.reason} for rejection in rejections
    ]
    payload["place_rejected_count"] = len(rejections)
    return payload


def _resolved_caches(caches: list[PlaceLookupRow | None]) -> list[PlaceLookupRow]:
    """Return resolved places in candidate order, once per Wikidata entity."""
    resolved: list[PlaceLookupRow] = []
    seen: set[str] = set()
    for cache in caches:
        if cache is None or cache.status != "resolved" or not cache.wikidata_id:
            continue
        if cache.wikidata_id in seen:
            continue
        seen.add(cache.wikidata_id)
        resolved.append(cache)
    return resolved


def _checked_at_utc(cache: PlaceLookupRow) -> datetime:
    checked_at = cache.checked_at
    return checked_at if checked_at.tzinfo is not None else checked_at.replace(tzinfo=UTC)


def _location_payload(cache: PlaceLookupRow) -> dict[str, Any]:
    return {
        "name": cache.label,
        "wikidata_id": cache.wikidata_id,
        "description": cache.description,
        "lat": cache.lat,
        "lon": cache.lon,
        "precision": cache.precision,
        "checked_at": _checked_at_utc(cache).isoformat(),
        "model": cache.resolver_version,
    }


def _payload_for_caches(
    payload: dict[str, Any],
    caches: list[PlaceLookupRow | None],
    *,
    complete: bool,
    rejections: tuple[PlaceCandidateRejection, ...] = (),
) -> dict[str, Any]:
    """Apply all independently verified places without duplicating the story."""
    enriched = _base_payload(payload)
    available = [cache for cache in caches if cache is not None]
    resolved = _resolved_caches(caches)
    all_resolved = (
        complete and bool(available) and all(cache.status == "resolved" for cache in available)
    )
    if not complete:
        status = "pending"
    elif resolved and all_resolved:
        status = "resolved" if len(resolved) == 1 else "resolved_multiple"
    elif resolved:
        status = "resolved_partial"
    elif any(cache.status == "ambiguous" for cache in available):
        status = "ambiguous"
    else:
        status = "no_match"
    checked_at = max((_checked_at_utc(cache) for cache in available), default=None)
    enriched.update(
        {
            "place_checked_at": checked_at.isoformat() if checked_at else None,
            "place_model": PLACE_METHOD_VERSION if complete else None,
            "place_resolution": status,
            "place_locations": [_location_payload(cache) for cache in resolved],
            "place_candidate_count": len(caches),
            "place_verified_count": len(resolved),
        }
    )
    if resolved:
        primary = resolved[0]
        enriched.update(
            {
                "geo_basis": "place",
                "geo_precision": primary.precision,
                "geo_source": "wikidata",
                "place_name": primary.label,
                "place_wikidata_id": primary.wikidata_id,
                "place_description": primary.description,
            }
        )
    return _with_rejections(enriched, rejections)


def _cache_is_usable(cache: PlaceLookupRow, now: datetime) -> bool:
    if cache.status == "resolved":
        return True
    return _checked_at_utc(cache) >= now - NEGATIVE_CACHE_TTL


def _event_context(event: Event) -> PlaceContext | None:
    city = event.payload.get("city")
    if not event.country:
        return None
    if city and event.lat is not None and event.lon is not None:
        return PlaceContext(country=event.country, city=str(city), lat=event.lat, lon=event.lon)
    return PlaceContext(country=event.country)


def _candidate_context(
    context: PlaceContext,
    candidates: tuple[PlaceCandidate, ...],
) -> PlaceContext:
    """Do not pretend one row-level city governs several named places."""
    if len(candidates) > 1:
        return PlaceContext(country=context.country)
    return context


def _restore_ingest_geo(row: EventRow) -> None:
    """Withdraw a place point without discarding retained ingest evidence."""
    from app.enrichment.geo import resolve_geo, resolved_news_scope
    from app.sources.rss_registry import load_feed_configs

    config = next((item for item in load_feed_configs() if item.source == row.source), None)
    payload = dict(row.payload or {})
    retained_country = row.country
    retained_city = str(payload.get("city") or "").strip() or None
    geo = (
        resolve_geo(retained_city, city_hint=retained_country)
        if retained_city
        else resolve_geo(
            str(payload.get("title") or ""),
            str(payload.get("summary") or ""),
            desk_country=config.desk_country if config else None,
            city_hint=config.default_country if config else retained_country,
        )
    )
    same_country = bool(retained_country and geo.iso == retained_country)
    supported_point = bool(same_country and geo.lat is not None and geo.lon is not None)
    row.country = retained_country
    row.lat = geo.lat if supported_point else None
    row.lon = geo.lon if supported_point else None
    if retained_city and supported_point:
        basis = "city"
    elif same_country:
        basis = geo.basis
    else:
        basis = "unknown" if retained_country else "none"
    payload.update(
        {
            "city": retained_city or (geo.city if supported_point else None),
            "geo_basis": basis,
            "news_scope": resolved_news_scope(
                retained_country,
                row.lat,
                row.lon,
                config.default_country if config else None,
            ),
        }
    )
    row.payload = payload


def _point_identity(
    wikidata_id: object, lat: object, lon: object
) -> tuple[str, float, float] | None:
    if not isinstance(lat, (str, int, float)) or not isinstance(lon, (str, int, float)):
        return None
    try:
        entity = str(wikidata_id or "")
        latitude, longitude = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (entity, latitude, longitude) if entity else None


def _payload_for_retained_locations(
    payload: dict[str, Any],
    locations: list[dict[str, Any]],
    evidence: PlaceExtraction,
) -> dict[str, Any]:
    """Promote the first still-proven location after false ones are removed."""
    clean = _base_payload(payload)
    primary = locations[0]
    # A rejected sibling changes candidate count and can therefore tighten the
    # lookup context from country-only to one city-anchored place. Requeue the
    # retained point so it must pass those stronger gates before v1.4 stamps it.
    complete = not evidence.rejections and len(locations) == len(evidence.candidates)
    clean.update(
        {
            "geo_basis": "place",
            "geo_precision": primary.get("precision"),
            "geo_source": "wikidata",
            "place_name": primary.get("name"),
            "place_wikidata_id": primary.get("wikidata_id"),
            "place_description": primary.get("description"),
            "place_checked_at": payload.get("place_checked_at"),
            "place_model": PLACE_METHOD_VERSION if complete else None,
            "place_resolution": (
                ("resolved" if len(locations) == 1 else "resolved_multiple")
                if complete
                else "pending"
            ),
            "place_locations": locations,
            "place_candidate_count": len(evidence.candidates),
            "place_verified_count": len(locations),
        }
    )
    return _with_rejections(clean, evidence.rejections)


def repair_generic_place_names(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Evict generic cache material and withdraw any points derived from it."""
    now = now or datetime.now(UTC)
    evicted = 0
    false_point_queries: dict[tuple[str, float, float], dict[str, str]] = {}
    possible_generic = func.lower(func.trim(PlaceLookupRow.query_text))
    cache_rows = session.execute(
        select(PlaceLookupRow).where(possible_generic.in_(_GENERIC_CACHE_QUERY_TEXTS))
    ).scalars()
    for cache in cache_rows:
        if _generic_place_reason(cache.query_text):
            if cache.wikidata_id and cache.lat is not None and cache.lon is not None:
                point = (cache.wikidata_id, cache.lat, cache.lon)
                false_point_queries.setdefault(point, {})[
                    normalise_place_name(cache.query_text)
                ] = cache.query_text
            session.delete(cache)
            evicted += 1

    if not false_point_queries:
        session.flush()
        return {"cache_rows_evicted": evicted, "event_rows_repaired": 0}

    false_points = set(false_point_queries)
    false_entity_ids = {point[0] for point in false_points}
    specific_support: dict[tuple[str, float, float], set[str]] = {}
    specific_rows = session.execute(
        select(PlaceLookupRow).where(PlaceLookupRow.wikidata_id.in_(false_entity_ids))
    ).scalars()
    for cache in specific_rows:
        if _generic_place_reason(cache.query_text):
            continue
        support_point = _point_identity(cache.wikidata_id, cache.lat, cache.lon)
        if support_point is not None:
            specific_support.setdefault(support_point, set()).add(
                normalise_place_name(cache.query_text)
            )

    repaired = 0
    basis_value = EventRow.payload["geo_basis"].as_string()
    rows = session.execute(
        select(EventRow)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.category == "news")
        .where(basis_value == "place")
    ).scalars()
    for row in rows:
        payload = dict(row.payload or {})
        evidence = extract_place_evidence(payload, city=payload.get("city"))
        candidate_names = {
            normalise_place_name(candidate.name) for candidate in evidence.candidates
        }

        def unsupported_generic_point(
            point: tuple[str, float, float] | None,
            supported_names: set[str] = candidate_names,
        ) -> bool:
            return bool(
                point in false_points and not (supported_names & specific_support.get(point, set()))
            )

        primary_point = _point_identity(payload.get("place_wikidata_id"), row.lat, row.lon)
        locations = [
            item for item in payload.get("place_locations") or [] if isinstance(item, dict)
        ]
        valid_locations = [
            item
            for item in locations
            if not unsupported_generic_point(
                _point_identity(item.get("wikidata_id"), item.get("lat"), item.get("lon"))
            )
        ]
        if not unsupported_generic_point(primary_point) and len(valid_locations) == len(locations):
            continue
        repair_rejections = list(evidence.rejections)
        rejected_keys = {normalise_place_name(item.name) for item in repair_rejections}
        rejected_points = [
            primary_point,
            *(
                _point_identity(item.get("wikidata_id"), item.get("lat"), item.get("lon"))
                for item in locations
            ),
        ]
        for rejected_point in rejected_points:
            if rejected_point is None or not unsupported_generic_point(rejected_point):
                continue
            for key, name in false_point_queries.get(rejected_point, {}).items():
                if key not in rejected_keys:
                    rejected_keys.add(key)
                    repair_rejections.append(
                        PlaceCandidateRejection(name=name, reason=GENERIC_PLACE_REASON)
                    )
        repair_evidence = PlaceExtraction(evidence.candidates, tuple(repair_rejections))
        if valid_locations:
            primary = valid_locations[0]
            row.lat, row.lon = float(primary["lat"]), float(primary["lon"])
            payload = _payload_for_retained_locations(payload, valid_locations, repair_evidence)
        else:
            _restore_ingest_geo(row)
            payload = dict(row.payload or {})
            if evidence.candidates:
                payload = _with_rejections(_base_payload(payload), repair_evidence.rejections)
                payload.update(
                    {
                        "place_resolution": "pending",
                        "place_candidate_count": len(evidence.candidates),
                        "place_verified_count": 0,
                    }
                )
            else:
                payload = _rejection_payload(payload, repair_evidence.rejections, checked_at=now)
        row.payload = payload
        repaired += 1
    session.flush()
    return {"cache_rows_evicted": evicted, "event_rows_repaired": repaired}


def apply_cached_places(events: list[Event], session: Session) -> list[Event]:
    """Reapply cached truth before every RSS upsert.

    This is what makes refresh safe: unchanged text produces the same cache key
    and exact point; changed text has no matching key and the ordinary RSS
    resolver authoritatively withdraws the old point (#741).
    """
    prepared: list[
        tuple[
            Event,
            PlaceContext | None,
            tuple[PlaceCandidate, ...],
            tuple[PlaceCandidateRejection, ...],
            list[str],
        ]
    ] = []
    keys: set[str] = set()
    for event in events:
        if not event.source.startswith("rss-") or event.category != Category.NEWS:
            prepared.append((event, None, (), (), []))
            continue
        context = _event_context(event)
        evidence = extract_place_evidence(event.payload, city=context.city if context else None)
        candidates = evidence.candidates
        lookup_context = _candidate_context(context, candidates) if context else None
        event_keys = (
            [lookup_key(candidate, lookup_context) for candidate in candidates]
            if lookup_context
            else []
        )
        keys.update(event_keys)
        prepared.append((event, context, candidates, evidence.rejections, event_keys))

    caches = (
        {
            row.lookup_key: row
            for row in session.execute(
                select(PlaceLookupRow).where(PlaceLookupRow.lookup_key.in_(keys))
            ).scalars()
        }
        if keys
        else {}
    )

    now = datetime.now(UTC)
    output: list[Event] = []
    for event, context, candidates, rejections, event_keys in prepared:
        if not event.source.startswith("rss-") or event.category != Category.NEWS:
            output.append(event)
            continue
        candidate_caches = [caches.get(key) for key in event_keys]
        candidate_caches = [
            cache if cache is not None and _cache_is_usable(cache, now) else None
            for cache in candidate_caches
        ]
        complete = bool(context and candidates) and all(
            cache is not None for cache in candidate_caches
        )
        if context and candidates:
            payload = _payload_for_caches(
                event.payload,
                candidate_caches,
                complete=complete,
                rejections=rejections,
            )
        elif rejections and not candidates:
            payload = _rejection_payload(event.payload, rejections, checked_at=now)
        else:
            payload = _with_rejections(_base_payload(event.payload), rejections)
        update: dict[str, Any] = {"payload": payload}
        resolved = _resolved_caches(candidate_caches)
        if resolved:
            update.update({"lat": resolved[0].lat, "lon": resolved[0].lon})
        output.append(event.model_copy(update=update))
    return output


def _row_context(row: EventRow) -> PlaceContext | None:
    city = (row.payload or {}).get("city")
    if not row.country:
        return None
    if city and row.lat is not None and row.lon is not None:
        return PlaceContext(country=row.country, city=str(city), lat=row.lat, lon=row.lon)
    return PlaceContext(country=row.country)


def _apply_caches_to_row(
    row: EventRow,
    caches: list[PlaceLookupRow | None],
    *,
    complete: bool,
    rejections: tuple[PlaceCandidateRejection, ...] = (),
) -> bool:
    before = (
        row.lat,
        row.lon,
        tuple(
            str(item.get("wikidata_id"))
            for item in (row.payload or {}).get("place_locations") or []
            if isinstance(item, dict)
        ),
    )
    resolved = _resolved_caches(caches)
    payload = _payload_for_caches(
        dict(row.payload or {}), caches, complete=complete, rejections=rejections
    )
    if resolved:
        row.lat, row.lon = resolved[0].lat, resolved[0].lon
    row.payload = payload
    after = (
        row.lat,
        row.lon,
        tuple(str(cache.wikidata_id) for cache in resolved),
    )
    return before != after


def _cache_row(
    key: str,
    candidate: PlaceCandidate,
    context: PlaceContext,
    verdict: PlaceVerdict,
    now: datetime,
) -> PlaceLookupRow:
    resolution = verdict.resolution
    return PlaceLookupRow(
        lookup_key=key,
        query_text=candidate.name,
        context_country=context.country,
        context_city=context.city or "",
        status=verdict.status,
        lat=resolution.lat if resolution else None,
        lon=resolution.lon if resolution else None,
        precision=resolution.precision if resolution else candidate.precision,
        wikidata_id=resolution.wikidata_id if resolution else None,
        label=resolution.label if resolution else None,
        description=resolution.description if resolution else None,
        checked_at=now,
        resolver_version=PLACE_METHOD_VERSION,
    )


def enrich_news_places(
    session: Session,
    *,
    limit: int,
    client: httpx.Client,
    now: datetime | None = None,
) -> dict[str, int]:
    """Resolve up to ``limit`` uncached names and update recent RSS rows."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    now = now or datetime.now(UTC)
    # Idempotent fallback for deployments that apply Alembic in offline mode:
    # the SQL stream cannot inspect live cache/event rows (#755).
    repair_generic_place_names(session, now=now)
    model_value = EventRow.payload["place_model"].as_string()
    rows = session.execute(
        select(EventRow)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.category == "news")
        .where(EventRow.occurred_at >= now - timedelta(days=30))
        .where(or_(model_value.is_(None), model_value != PLACE_METHOD_VERSION))
        .order_by(EventRow.occurred_at.desc())
        .limit(max(PLACE_SCAN_LIMIT, limit * 200))
    ).scalars()

    stats = {
        "scanned": 0,
        "lookups": 0,
        "cache_hits": 0,
        "enriched": 0,
        "multiple": 0,
        "partial": 0,
        "verified_locations": 0,
        "no_candidate": 0,
        "no_context": 0,
        "errors": 0,
    }
    memory_cache: dict[str, PlaceLookupRow] = {}
    for row in rows:
        payload = dict(row.payload or {})
        stats["scanned"] += 1
        evidence = extract_place_evidence(payload, city=payload.get("city"))
        candidates = evidence.candidates
        if (
            evidence.rejections
            and not candidates
            and str(payload.get("geo_basis") or "") == "place"
        ):
            _restore_ingest_geo(row)
            payload = dict(row.payload or {})
        if evidence.rejections and not candidates:
            row.payload = _rejection_payload(payload, evidence.rejections, checked_at=now)
            stats["no_candidate"] += 1
            continue

        context = _row_context(row)
        if context is None:
            payload = _base_payload(payload)
            payload.update(
                {
                    "place_checked_at": now.isoformat(),
                    "place_model": PLACE_METHOD_VERSION,
                    "place_resolution": "no_context",
                }
            )
            row.payload = _with_rejections(payload, evidence.rejections)
            stats["no_context"] += 1
            continue

        if not candidates:
            payload = _base_payload(payload)
            payload.update(
                {
                    "place_checked_at": now.isoformat(),
                    "place_model": PLACE_METHOD_VERSION,
                    "place_resolution": "no_candidate",
                }
            )
            row.payload = _with_rejections(payload, evidence.rejections)
            stats["no_candidate"] += 1
            continue
        stats["multiple"] += int(len(candidates) > 1)
        lookup_context = _candidate_context(context, candidates)

        candidate_caches: list[PlaceLookupRow | None] = []
        for candidate in candidates:
            key = lookup_key(candidate, lookup_context)
            cache = memory_cache.get(key) or session.get(PlaceLookupRow, key)
            if cache is not None and _cache_is_usable(cache, now):
                memory_cache[key] = cache
                stats["cache_hits"] += 1
                candidate_caches.append(cache)
                continue

            if stats["lookups"] >= limit:
                # A None slot keeps the row eligible and preserves candidate order.
                candidate_caches.append(None)
                continue
            stats["lookups"] += 1
            try:
                verdict = resolve_wikidata_place(candidate, lookup_context, client=client)
            except (httpx.HTTPError, ValueError, TypeError):
                stats["errors"] += 1
                candidate_caches.append(None)
                continue

            if cache is None:
                cache = _cache_row(key, candidate, lookup_context, verdict, now)
                session.add(cache)
            else:
                replacement = _cache_row(key, candidate, lookup_context, verdict, now)
                for field in (
                    "status",
                    "lat",
                    "lon",
                    "precision",
                    "wikidata_id",
                    "label",
                    "description",
                    "checked_at",
                    "resolver_version",
                ):
                    setattr(cache, field, getattr(replacement, field))
            memory_cache[key] = cache
            candidate_caches.append(cache)

        complete = all(cache is not None for cache in candidate_caches)
        resolved = _resolved_caches(candidate_caches)
        stats["verified_locations"] += len(resolved)
        stats["partial"] += int(
            complete
            and bool(resolved)
            and any(cache is not None and cache.status != "resolved" for cache in candidate_caches)
        )
        stats["enriched"] += int(
            _apply_caches_to_row(
                row,
                candidate_caches,
                complete=complete,
                rejections=evidence.rejections,
            )
        )
    return stats


#: The evidence `geo_basis='place'` claims: at least one verified location on
#: the row itself. A basis is a statement about why a coordinate is there, so a
#: row that cannot show the statement must not make it (#756).
PLACE_EVIDENCE_FIELD = "place_locations"


def place_evidence_holds(payload: dict[str, Any]) -> bool:
    """Does this payload back the basis it claims?

    Only `place` is interrogated. Every other basis names evidence that lives
    elsewhere — a gazetteer hit, a term match, a feed's own desk — and asking
    those for a verified location would reject rows that are perfectly honest.

    `place_locations` is the authority rather than `place_verified_count`: the
    count is a summary of the list, and a summary cannot outvote the thing it
    summarises. The row that prompted this carried a count of zero *and* an
    empty list, but a migration that updated one and not the other is exactly
    the failure mode to design against.
    """
    if str(payload.get("geo_basis") or "") != "place":
        return True
    locations = payload.get(PLACE_EVIDENCE_FIELD)
    return isinstance(locations, list) and len(locations) > 0


def without_unbacked_place(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip a `place` basis the payload cannot support, keeping everything else.

    The demotion is recorded rather than silent: `place_demoted` says why the
    basis went, so a row that lost its point can be told apart from one that
    never had a place claim. The country stays — losing the building is not
    losing the story, and it must remain reachable by clicking the country.
    """
    if place_evidence_holds(payload):
        return payload
    demoted = dict(payload)
    demoted["geo_basis"] = "city" if demoted.get("city") else "none"
    demoted["place_demoted"] = "no_verified_location"
    for field in ("place_name", "place_wikidata_id", "place_description", "geo_source"):
        demoted.pop(field, None)
    return demoted
