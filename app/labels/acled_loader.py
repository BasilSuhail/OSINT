"""Loader layer — ACLED weekly regional xlsx exports → tidy rows.

Reads every ``*aggregated_data*.xlsx`` in a directory (the public ACLED
"aggregated data" regional downloads: one row per WEEK x COUNTRY x ADMIN1 x
EVENT_TYPE x SUB_EVENT_TYPE). Country names map to ISO2 via the shared
enrichment table; unmapped names are counted and skipped, never guessed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openpyxl

from app.enrichment.country_codes import country_name_to_iso2

_GLOB = "*aggregated_data*.xlsx"
_REQUIRED_COLUMNS = ("WEEK", "COUNTRY", "EVENT_TYPE", "EVENTS")

#: Sovereign states ACLED names that the shared admin0 geojson lacks (or spells
#: differently). Dependent territories and water bodies are deliberately absent:
#: the country panel is sovereign-state level. Kosovo gets its customary
#: user-assigned code XK.
_ACLED_NAME_TO_ISO2: dict[str, str] = {
    "Democratic Republic of Congo": "CD",
    "Republic of Congo": "CG",
    "Taiwan": "TW",
    "Bahrain": "BH",
    "Norway": "NO",
    "Kosovo": "XK",
    "Singapore": "SG",
    "Malta": "MT",
    "Mauritius": "MU",
    "Maldives": "MV",
    "Cape Verde": "CV",
    "Comoros": "KM",
    "Sao Tome and Principe": "ST",
    "Antigua and Barbuda": "AG",
    "Dominica": "DM",
    "Saint Lucia": "LC",
    "Saint Kitts and Nevis": "KN",
    "Saint Vincent and the Grenadines": "VC",
    "Barbados": "BB",
    "Grenada": "GD",
    "Seychelles": "SC",
    "Andorra": "AD",
    "San Marino": "SM",
    "Monaco": "MC",
    "Liechtenstein": "LI",
    "Vatican City": "VA",
    "Samoa": "WS",
    "Tonga": "TO",
    "Kiribati": "KI",
    "Nauru": "NR",
    "Palau": "PW",
    "Micronesia": "FM",
    "Marshall Islands": "MH",
    "Tuvalu": "TV",
}


@dataclass
class AcledLoadResult:
    """Tidy rows plus everything the run summary needs to report."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    unmapped_countries: Counter[str] = field(default_factory=Counter)
    skipped_rows: int = 0


def load_acled_weekly(directory: Path | str) -> AcledLoadResult:
    """Load all weekly regional aggregate files under `directory`.

    Raises FileNotFoundError when the directory or any matching file is
    missing — the labeler must fail loudly rather than write a partial or
    empty label set.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"ACLED directory not found: {directory}")
    paths = sorted(directory.glob(_GLOB))
    if not paths:
        raise FileNotFoundError(f"no {_GLOB} files in {directory}")

    result = AcledLoadResult()
    for path in paths:
        _load_file(path, result)
        result.files_read.append(path.name)
    return result


def _load_file(path: Path, result: AcledLoadResult) -> None:
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        sheet = workbook.active
        # ACLED exports declare a bogus <dimension ref="A1"/>; read-only mode
        # trusts it and yields single-cell rows unless dimensions are reset.
        sheet.reset_dimensions()
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return
        index = {name: i for i, name in enumerate(header) if isinstance(name, str)}
        if any(col not in index for col in _REQUIRED_COLUMNS):
            return  # not a weekly regional file (e.g. a country-year summary)

        for raw in rows:
            parsed = _parse_row(raw, index)
            if parsed is None:
                result.skipped_rows += 1
                continue
            country_name, tidy = parsed
            iso2 = country_name_to_iso2(country_name) or _ACLED_NAME_TO_ISO2.get(country_name)
            if iso2 is None:
                result.unmapped_countries[country_name] += 1
                continue
            tidy["country"] = iso2
            result.rows.append(tidy)
    finally:
        workbook.close()


def _parse_row(raw: tuple[Any, ...], index: dict[str, int]) -> tuple[str, dict[str, Any]] | None:
    def cell(name: str) -> Any:
        i = index.get(name)
        return raw[i] if i is not None and i < len(raw) else None

    week = cell("WEEK")
    country = cell("COUNTRY")
    event_type = cell("EVENT_TYPE")
    events = cell("EVENTS")
    if not isinstance(week, datetime) or not country or not event_type or events is None:
        return None
    fatalities = cell("FATALITIES")
    return str(country), {
        "week": week.replace(tzinfo=UTC) if week.tzinfo is None else week.astimezone(UTC),
        "event_type": str(event_type),
        "events": int(events),
        "fatalities": int(fatalities) if fatalities is not None else 0,
    }
