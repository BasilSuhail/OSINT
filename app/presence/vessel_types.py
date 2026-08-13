"""What a vessel is, read from the type it broadcasts (#954).

AIS carries the ship type in the static message every vessel sends, so the
categories a reader filters by are transmitted rather than inferred. That is
the whole reason this layer can offer "fishing" and "tankers" as separate
switches without a model, a guess or a lookup table of names.

The codes are the ITU allocation. Measured in one live sample of 1,203 vessels
on 2026-08-13: 380 cargo, 223 passenger, 141 tanker, 121 tugs, 92 pilot craft,
83 with the "other" code, 53 search and rescue, 27 sending nothing at all, 13
pleasure craft, 12 sailing, 10 dredgers.
"""

from __future__ import annotations

Category = str

#: The categories, in the order a reader would look for them.
CATEGORIES: tuple[Category, ...] = (
    "cargo",
    "tanker",
    "passenger",
    "fishing",
    "pleasure",
    "service",
    "other",
)


def category_for(ship_type: int | None) -> Category:
    """The category for a broadcast ship type.

    ``other`` is what a vessel gets when it sent nothing, sent zero — which the
    standard defines as "not available" — or sent a code the allocation leaves
    unassigned. It is a real answer: a vessel that will not say what it is has
    said something, and inventing a category for it would put it on a filter
    row that nothing measured.
    """
    if ship_type is None:
        return "other"
    if ship_type == 30:
        return "fishing"
    if 36 <= ship_type <= 37:
        return "pleasure"
    #: Towing, dredging, diving, military operations and every service craft:
    #: pilots, tugs, search and rescue, law enforcement, anti-pollution. One
    #: row, because a reader watching a port wants the working boats separated
    #: from the trade, not sorted into eleven kinds of working boat.
    if 31 <= ship_type <= 35 or 50 <= ship_type <= 59:
        return "service"
    #: High-speed craft. Ferries, in practice, which is why they sit with the
    #: passenger ships rather than in a category of their own.
    if 40 <= ship_type <= 49 or 60 <= ship_type <= 69:
        return "passenger"
    if 70 <= ship_type <= 79:
        return "cargo"
    if 80 <= ship_type <= 89:
        return "tanker"
    return "other"


#: Navigational status, in the words the standard means. Only the ones a reader
#: would act on are named; the rest are absent rather than guessed at, and an
#: absent status is drawn as no status.
NAV_STATUS: dict[int, str] = {
    0: "under way",
    1: "at anchor",
    2: "not under command",
    3: "restricted manoeuvrability",
    4: "constrained by draught",
    5: "moored",
    6: "aground",
    7: "fishing",
    8: "under way sailing",
}


def nav_status_for(code: int | None) -> str | None:
    """What the vessel says it is doing, or nothing.

    Code 15 is "undefined" and several others are reserved. A vessel that has
    not said what it is doing must read as silent, not as "under way".
    """
    if code is None:
        return None
    return NAV_STATUS.get(code)
