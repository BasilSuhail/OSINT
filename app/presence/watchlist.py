"""What an aircraft is for, and which aircraft are being watched (#954).

Two questions are worth asking of a live traffic feed: what is in the air over
there, and where is *that* aircraft. The military list answers the first. This
module is the second, plus the role that makes the first legible — a feed of
four hundred marks in one colour tells a reader who already knows the type
designators by heart exactly as much as it tells one who does not.

Nothing here is stored. The watchlist is read from a file the operator points
at and is never part of the repository: it carries identifiers and the job an
airframe does, which is operational data, not code. The ledger below is this
process's memory of what it has seen since it started, and it says so.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import dataclass
from typing import Any

#: Where the operator's watchlist lives. Unset means no watchlist, which is a
#: working configuration and not a fault — the layer draws routine traffic
#: exactly as it did before.
WATCHLIST_PATH_ENV = "PRESENCE_WATCHLIST_PATH"

#: Looked at when the environment says nothing, in this order. A file dropped
#: in either place needs no variable set, which is the difference between a
#: feature an operator can try and one they have to be told how to switch on.
#:
#: `/data` first, because the API normally runs in a container and that is
#: where the repository's `data/` directory is mounted — the working directory
#: in there is `/app`, so the relative path alone could never find a file the
#: operator had just written (#959). The relative one stays for a host-run
#: process, where `/data` does not exist. Both are git-ignored.
WATCHLIST_SEARCH_PATHS = ("/data/watchlist.json", "data/watchlist.json")

#: Kept as the name of the path an operator is told to write. It is the second
#: entry above because it is the one that exists on a host run.
WATCHLIST_DEFAULT_PATH = "data/watchlist.json"

#: An aircraft the console has not heard from in this long is off the ledger.
#: Long enough to survive a gap in receiver coverage mid-flight, short enough
#: that the next sighting is a new flight rather than a resumed one.
LEDGER_GRACE_S = 45 * 60

Role = str

#: Roles read off the ICAO type designator. Grouped by what a reader watching a
#: border would want separated, not by what a procurement office would.
_ROLES: dict[Role, frozenset[str]] = {
    "tanker": frozenset({"K35R", "KC10", "KC30", "KC46", "A332", "A310", "IL78", "VC10", "TRIS"}),
    "isr": frozenset(
        {
            "E3TF",
            "E3CF",
            "E6",
            "E2",
            "E8",
            "R135",
            "RC35",
            "U2",
            "RQ4",
            "MQ9",
            "MQ4",
            "P8",
            "P3",
            "CL60",
            "SW4",
            "B350",
            "DH8D",
            "AN30",
            "SR71",
            "GLF5",
            "E145",
        }
    ),
    "fighter": frozenset(
        {
            "F16",
            "F15",
            "F18",
            "F22",
            "F35",
            "F5",
            "F4",
            "A10",
            "AV8B",
            "EUFI",
            "RFAL",
            "TOR",
            "GRIP",
            "MG29",
            "MG31",
            "SU24",
            "SU25",
            "SU27",
            "SU30",
            "SU34",
            "SU57",
            "J10",
            "J11",
            "J20",
            "B1",
            "B2",
            "B52",
            "TU95",
            "TU22",
            "TU16",
        }
    ),
    "trainer": frozenset(
        {
            "T38",
            "T6",
            "AT6",
            "TEX2",
            "HAWK",
            "M346",
            "M345",
            "L39",
            "AJET",
            "PC21",
            "PC9",
            "PC7",
            "G115",
            "G120",
            "K8",
            "SF26",
            "DA40",
            "DA42",
            "DA62",
            "Z42",
        }
    ),
    "transport": frozenset(
        {
            "C130",
            "C30J",
            "C160",
            "C17",
            "C5",
            "C5M",
            "C27J",
            "C295",
            "CN35",
            "A400",
            "C47",
            "AN12",
            "AN26",
            "AN28",
            "AN72",
            "AN24",
            "IL76",
            "IL62",
            "L410",
            "DHC6",
            "DH8A",
            "SB20",
            "SF34",
            "SH36",
            "G12T",
            "A319",
            "A320",
            "A321",
            "B737",
            "B738",
            "B752",
            "B762",
            "B763",
            "PC12",
            "BE20",
            "C12",
            "C560",
            "C56X",
            "C680",
            "C750",
            "F900",
            "F2TH",
            "GLF4",
            "GLF6",
            "LJ35",
            "RJ1H",
        }
    ),
}

#: Whole families that are rotorcraft. The same rule the map's silhouette uses,
#: so the shape a reader sees and the role a card prints never disagree about
#: the same aircraft.
_ROTORCRAFT_PREFIXES = ("H", "EC", "MI", "KA")
_ROTORCRAFT_NAMES = frozenset(
    {
        "A109",
        "A119",
        "A129",
        "A139",
        "A149",
        "A169",
        "A189",
        "AS32",
        "AS3B",
        "AS50",
        "AS55",
        "AS65",
        "ALO2",
        "ALO3",
        "LAMA",
        "GAZL",
        "PUMA",
        "BK17",
        "S61",
        "S64",
        "S70",
        "S76",
        "S92",
        "B06",
        "B212",
        "B407",
        "B412",
        "B429",
        "B505",
        "R22",
        "R44",
        "R66",
        "EXPL",
        "NH90",
        "EH10",
        "LYNX",
        "WASP",
        "SCOU",
        "TIGR",
        "W3",
        "V22",
    }
)
#: Business jets that sit inside the H-and-a-digit family and are not rotorcraft.
_ROTORCRAFT_EXCEPTIONS = ("H25",)


def _rotorcraft(code: str) -> bool:
    if code in _ROTORCRAFT_NAMES:
        return True
    if code.startswith(_ROTORCRAFT_EXCEPTIONS):
        return False
    for prefix in _ROTORCRAFT_PREFIXES:
        rest = code[len(prefix) :]
        if code.startswith(prefix) and rest[:1].isdigit():
            return True
    return False


def role_for(type_code: str | None) -> Role:
    """What the airframe is for, or ``other`` when its designator says nothing.

    ``other`` is a real answer. A designator this module has never been taught
    is not a transport by default, and calling it one would put a role on a
    card that nothing measured.
    """
    code = (type_code or "").strip().upper()
    if not code:
        return "other"
    if _rotorcraft(code):
        return "rotorcraft"
    for role, codes in _ROLES.items():
        if code in codes:
            return role
    return "other"


@dataclass(frozen=True)
class WatchEntry:
    """Why an airframe is worth pulling out of the traffic.

    ``label`` is what the aircraft is *for* — an office, a fleet, a job. It is
    never a person. Who is aboard is not a question this console answers, and
    an aircraft is not a proxy for one.
    """

    label: str
    category: str


@dataclass(frozen=True)
class WatchRule:
    """A watch on a kind of flying rather than on one airframe.

    Identifiers are the precise way to watch something and the worst way to
    start: a reader who wants "the tankers" or "the airlift callsigns" has to
    go and find thirty hex codes first, and the list is stale by the next
    sortie. A rule watches the behaviour instead, and the behaviour is already
    on every row.
    """

    #: One of ``callsign_prefix``, ``role``, ``type``.
    field: str
    value: str
    entry: WatchEntry


@dataclass(frozen=True)
class Watchlist:
    """What is being watched: exact airframes, and rules over the traffic."""

    exact: dict[str, WatchEntry]
    rules: tuple[WatchRule, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.exact) or bool(self.rules)

    @property
    def size(self) -> int:
        """Distinct watches, for the count the rail prints.

        Labels, not keys: one airframe listed by both hex and registration is
        one watch, and so is one rule however many aircraft it catches.
        """
        labels = {(e.label, e.category) for e in self.exact.values()}
        labels |= {(r.entry.label, r.entry.category) for r in self.rules}
        return len(labels)


EMPTY_WATCHLIST = Watchlist(exact={}, rules=())

#: The rule fields a file may use, and the row field each one reads.
_RULE_FIELDS = {"callsign_prefix": "callsign", "role": "role", "type": "type"}


def _entry_from(raw: Any) -> tuple[list[str], list[WatchRule], WatchEntry] | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    if not label:
        return None
    category = str(raw.get("category") or "other").strip().lower()
    if category not in {"state", "vip", "other"}:
        category = "other"
    entry = WatchEntry(label=label, category=category)
    keys = [
        str(raw[field]).strip().upper()
        for field in ("hex", "registration")
        if isinstance(raw.get(field), str) and str(raw[field]).strip()
    ]
    rules = [
        WatchRule(field=field, value=str(raw[field]).strip().upper(), entry=entry)
        for field in _RULE_FIELDS
        if isinstance(raw.get(field), str) and str(raw[field]).strip()
    ]
    if not keys and not rules:
        return None
    return keys, rules, entry


def load_watchlist_from_entries(raw: list) -> Watchlist:
    """A watchlist from already-parsed entries.

    Separate from the file reader so the shape can be exercised — by a test, or
    by the example the repository ships — without a file having to exist.
    """
    exact: dict[str, WatchEntry] = {}
    rules: list[WatchRule] = []
    for item in raw:
        parsed = _entry_from(item)
        if parsed is None:
            continue
        keys, item_rules, entry = parsed
        for key in keys:
            exact[key] = entry
        rules.extend(item_rules)
    return Watchlist(exact=exact, rules=tuple(rules))


def load_watchlist(path: str | None) -> Watchlist:
    """The operator's watchlist: exact airframes and rules over the traffic.

    Every failure is an empty watchlist rather than an exception. A missing
    file, an unreadable one and a malformed one all mean the same thing to the
    reader — no aircraft are being watched — and none of them is a reason for
    the live layer to stop drawing routine traffic.
    """
    if not path:
        return EMPTY_WATCHLIST
    try:
        raw = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return EMPTY_WATCHLIST
    if not isinstance(raw, list):
        return EMPTY_WATCHLIST
    return load_watchlist_from_entries(raw)


#: What the layer watches when nobody has said otherwise.
#:
#: Rules only, and only ones that describe a job rather than an airframe: a
#: shipped list of identifiers would be a curated claim about particular
#: aircraft, maintained by nobody and stale by the next sortie. These two are
#: derived from the type designator the feed already sends, they are true
#: everywhere, and they are the two roles whose movement is worth noticing
#: without knowing anything else — the tankers say where an air force intends
#: to reach, and the surveillance aircraft say where it is looking.
#:
#: A file at either search path replaces this entirely. Nobody has to accept
#: somebody else's idea of what is interesting, but nobody has to run a
#: command before the layer does anything either.
DEFAULT_WATCH_ENTRIES: tuple[dict[str, str], ...] = (
    {"role": "tanker", "label": "air-to-air refuelling", "category": "other"},
    {"role": "isr", "label": "surveillance", "category": "other"},
)

#: What happened when the watchlist was last looked for. `ok` covers both a
#: file that loaded and a console nobody has configured; `unreadable` is the
#: one worth saying out loud, because it means somebody asked for a file and
#: did not get it.
#: A list somebody wrote is in force.
WATCHLIST_OK = "ok"
#: The built-in list is in force. Worth saying on screen: a reader is owed the
#: difference between "these are the aircraft you asked for" and "these are the
#: ones this console watches until told otherwise".
WATCHLIST_DEFAULT = "default"


def resolve_watchlist() -> tuple[Watchlist, str]:
    """What is being watched, and whether anybody chose it.

    The layer always watches something. A file wins when there is a readable
    one — a named path first, then the two conventional places — and otherwise
    the built-in list is in force.

    An earlier version refused to fall back from a named path that could not be
    read, on the grounds that a typo should not quietly load something else.
    That is a defensible rule and it made the common case worse: a stale line
    in a settings file left the layer drawing nothing at all, which is
    indistinguishable from broken. Nothing here is evidence and nothing is
    cited, so the console draws its own list and says on screen that the list
    is its own.
    """
    configured = (os.environ.get(WATCHLIST_PATH_ENV) or "").strip()
    candidates = ([configured] if configured else []) + list(WATCHLIST_SEARCH_PATHS)
    for candidate in candidates:
        if not pathlib.Path(candidate).is_file():
            continue
        loaded = load_watchlist(candidate)
        if loaded:
            return loaded, WATCHLIST_OK

    return load_watchlist_from_entries(list(DEFAULT_WATCH_ENTRIES)), WATCHLIST_DEFAULT


def watchlist_from_env() -> Watchlist:
    return resolve_watchlist()[0]


def example_entries() -> list[dict[str, str]]:
    """The shape of the file, as the repository ships it.

    Kept in code rather than only in a JSON file so a test can hold it to the
    same rule the real list is held to: an office, never a person.
    """
    return [
        {
            "hex": "000000",
            "label": "head of state transport",
            "category": "state",
        },
        {
            "registration": "N000EX",
            "label": "chartered executive transport",
            "category": "vip",
        },
        #: A rule rather than an airframe: everything the feed shows doing this
        #: job, without a single identifier having to be looked up first.
        {"role": "tanker", "label": "air-to-air refuelling", "category": "other"},
        {"callsign_prefix": "RCH", "label": "strategic airlift", "category": "other"},
    ]


def match(row: dict, watchlist: Watchlist) -> WatchEntry | None:
    """The watchlist entry for one aircraft: named airframes first, then rules.

    The hex is the address the transponder itself sends. The registration is a
    lookup the aggregator did against a public register, and it is occasionally
    a guess, so it never overrides an identifier the aircraft transmitted — and
    a named airframe always outranks a rule, because somebody typed it out on
    purpose and the rule is a standing interest.
    """
    if not watchlist:
        return None
    for field in ("hex", "registration"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            hit = watchlist.exact.get(value.strip().upper())
            if hit is not None:
                return hit
    for rule in watchlist.rules:
        value = row.get(_RULE_FIELDS[rule.field])
        if not isinstance(value, str) or not value.strip():
            continue
        seen = value.strip().upper()
        #: A callsign is a prefix and a fleet: RCH is every airlift sortie,
        #: and matching the whole string would watch exactly one flight that
        #: has probably already landed.
        if rule.field == "callsign_prefix":
            if seen.startswith(rule.value):
                return rule.entry
        elif seen == rule.value:
            return rule.entry
    return None


#: key -> (first seen airborne, last seen at). Module state on purpose: it is
#: this process's memory and it is meant to die with the process.
_ledger: dict[str, tuple[float, float]] = {}


def clear_ledger() -> None:
    """Forget everything seen. Tests need this; a restart does it for free."""
    _ledger.clear()


def note_airborne(key: str, *, alt_ft: float | None, now: float | None = None) -> float | None:
    """Record a sighting and return when this aircraft was first seen flying.

    ``None`` altitude is an aircraft on the ground — the feed sends the string
    "ground" and the normaliser turns that into no number at all — and the
    clock must not start there, or a parked aircraft would read as having been
    airborne since the console booted.
    """
    stamp = time.time() if now is None else now
    if alt_ft is None:
        return None
    first, _ = _ledger.get(key, (stamp, stamp))
    _ledger[key] = (first, stamp)
    return first


def forget_stale(now: float | None = None, grace_s: float = LEDGER_GRACE_S) -> None:
    """Drop aircraft not heard from for a while.

    Without this, a gap of hours would be reported as one continuous flight,
    which is the kind of number a reader would take for a measurement.
    """
    stamp = time.time() if now is None else now
    for key, (_, last) in list(_ledger.items()):
        if stamp - last > grace_s:
            del _ledger[key]
