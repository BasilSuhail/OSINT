"""The harm scale, and the verdict every source must produce (#591).

Two rules, both learned the hard way.

**Every score states its reason.** #574, #577, #579 and #586 were each a number
nobody could interrogate: a value that looked plausible at every layer except
the one that used it. A score with no stated reason is the failure this module
exists to prevent, so `Verdict` refuses to be constructed without one.

**Harsh means refusing to soften real harm — not inflating everything.** #580
found 55% of hazard country-months pinned at 0.90, which discriminates exactly
as poorly as a floor of zeros. The bands below are *floors*: a confirmed death
can never read as routine, while routine news genuinely lands low and the scale
keeps its ability to tell them apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Any confirmed death floors here — below this the scale is claiming nobody
#: died. The band starting here is named "grave" rather than "lethal" because a
#: serious armed attack belongs in it too, whether or not deaths are confirmed
#: yet. Naming the band "lethal" made the model look wrong when it was right.
LETHAL_FLOOR: float = 0.60

#: Ten or more deaths, a massacre, or a mass-fatality disaster floors here.
MASS_CASUALTY_FLOOR: float = 0.80


@dataclass(frozen=True)
class Band:
    """One band of the harm scale. `lower` inclusive, `upper` exclusive."""

    name: str
    lower: float
    upper: float
    meaning: str


#: The scale. Tiles [0, 1] with no gaps — every value belongs to exactly one band.
BANDS: tuple[Band, ...] = (
    Band("routine", 0.00, 0.20, "policy, business, sport — nothing happened to anyone"),
    Band("tension", 0.20, 0.40, "protest, strike, diplomatic rupture — no violence"),
    Band("violence", 0.40, LETHAL_FLOOR, "violence without confirmed death, or mass displacement"),
    Band(
        "grave",
        LETHAL_FLOOR,
        MASS_CASUALTY_FLOOR,
        "confirmed deaths (1-9), or serious armed attack",
    ),
    Band("mass_casualty", MASS_CASUALTY_FLOOR, 1.00, "10+ dead, massacre, mass-fatality disaster"),
)


def band_for(value: float) -> Band:
    """The band a severity falls in. 1.0 belongs to the top band."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"severity {value} outside [0, 1]")
    for band in BANDS:
        if value < band.upper:
            return band
    return BANDS[-1]


#: Words that soften what happened. Refused above the lethal floor, where the
#: whole point is to say plainly that people were killed. Below it they are
#: often the accurate word, so they are left alone.
_EUPHEMISMS: tuple[str, ...] = (
    "incident",
    "situation",
    "event took place",
    "unfortunate",
    "disturbance",
    "altercation",
    "unrest occurred",
)


def euphemism_in(rationale: str, *, value: float) -> str | None:
    """The first softening word in a rationale that should be blunt, or None.

    Only applies at or above the lethal floor: "a routine incident" is the
    correct description of a routine incident.
    """
    if value < LETHAL_FLOOR:
        return None
    lowered = rationale.lower()
    for word in _EUPHEMISMS:
        if re.search(rf"\b{re.escape(word)}", lowered):
            return word
    return None


@dataclass(frozen=True)
class Verdict:
    """A severity together with why it holds that value, and what produced it.

    Constructing one without a rationale raises. That is deliberate: an
    unexplained number is the thing this module exists to stop.
    """

    value: float
    rationale: str
    method: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"severity {self.value} outside [0, 1]")
        if not self.rationale or not self.rationale.strip():
            raise ValueError("a severity must state its reason")

    @property
    def band(self) -> str:
        return band_for(self.value).name

    def as_payload(self) -> dict[str, str]:
        """The keys a fetcher merges into `Event.payload`.

        Stored in the payload rather than as columns: it is explanatory
        metadata, it needs no migration, and nothing queries on it.
        """
        return {
            "severity_rationale": self.rationale.strip(),
            "severity_method": self.method,
            "severity_band": self.band,
        }
