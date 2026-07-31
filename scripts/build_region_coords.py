"""Build ``app/enrichment/data/region_coords.json`` from Natural Earth (#717).

The resolver already recognises ~276 subnational regions — Wales, Bavaria,
Kerala, Sindh — but only ever used them to infer a country, then threw the
place away. A story saying "Drought declared across Wales" knew it was in
Wales and still landed with no coordinates, which since #719 means no dot
at all.

This gives each region a point, so those stories pin in Wales rather than
nowhere. A region centroid is coarser than a city, and it is honest: the
story really is about that region.

Run this only when the region list in ``geo_terms.json`` changes. The
14 MB source archive is downloaded to a temp dir and discarded; only the
~250-entry JSON is committed, so the runtime carries no new dependency
and the repo carries no new bulk.

Usage:
    python -m scripts.build_region_coords [--out PATH]

Source: Natural Earth 10m Admin-1 States/Provinces, public domain.
https://www.naturalearthdata.com/downloads/10m-cultural-vectors/
"""

from __future__ import annotations

import argparse
import json
import struct
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip"
DBF_NAME = "ne_10m_admin_1_states_provinces.dbf"

_DATA = Path(__file__).resolve().parent.parent / "app" / "enrichment" / "data"
TERMS_PATH = _DATA / "geo_terms.json"
CITIES_PATH = _DATA / "cities.json"
DEFAULT_OUT = _DATA / "region_coords.json"

#: Disambiguating suffixes this project adds so a term is unambiguous in
#: prose ("washington state", so a bare "Washington" is not the capital).
#: Natural Earth does not use them.
SUFFIXES = (
    " state",
    " province",
    " region",
    " county",
    " canton",
    " emirate",
    " division",
    " prefecture",
    " governorate",
)

#: English exonym → the local name Natural Earth files it under. Only the
#: ones the plain match misses; not a general transliteration table.
ALIASES = {
    "sicily": "sicilia",
    "catalonia": "cataluña",
    "andalusia": "andalucía",
    "basque country": "país vasco",
    "normandy": "normandie",
    "alsace": "alsace",
    "flanders": "vlaanderen",
    "wallonia": "wallonie",
    "scania": "skåne",
    "silesia": "śląskie",
    "masovia": "mazowieckie",
    "java": "jawa barat",
    "sumatra": "sumatera utara",
    "sulawesi": "sulawesi selatan",
    "kyushu": "fukuoka",
    "baden wurttemberg": "baden-württemberg",
    "yorkshire": "north yorkshire",
    "mindanao": "davao del sur",
    "luzon": "bulacan",
    "visayas": "cebu",
    "isan": "khon kaen",
    "mekong delta": "can tho",
    "niger delta": "rivers",
    "sinai": "north sinai",
    "upper egypt": "asyut",
    "hijaz": "makkah",
    "darfur": "north darfur",
    "kordofan": "north kordofan",
    "matabeleland": "matabeleland north",
    "mashonaland": "mashonaland east",
    "anbar": "al anbar",
    "basra": "al basrah",
    "hodeidah": "al hudaydah",
    "kowloon": "kowloon city",
    "munster": "cork",
    "leinster": "dublin",
    "connacht": "galway",
    "negev": "hadarom",
    "galilee": "hazafon",
    "golan heights": "hazafon",
    "siberia": "krasnoyarsk",
    "patagonia": "chubut",
    "donbas": "donets'k",
    "khan younis": "khan yunis",
    "kurdistan region": "arbil",
    # Natural Earth files this under the Turkish spelling, dotless i and all.
    "kurdistan region of turkey": "diyarbakır",  # noqa: RUF001
    "aleppo": "halab",
    "mosul": "ninawa",
    "isfahan": "esfahan",
    "yucatan": "yucatán",
    "parana": "paraná",
    "cordoba": "córdoba",
    "zurich": "zürich",
    "geneva": "genève",
    "lublin": "lubelskie",
    "valencia": "valenciana",
}

#: Regions that stand in for their whole country, so a pin on them is a
#: country pin by another name — the blob #719 removed.
#:
#: England holds ~84% of the United Kingdom's people and ~54% of its
#: land, and its centroid lands 1.87° from the UK's own; 33 stories
#: piled onto that single point in a week.
#: In UK copy "England" is used the way "Britain" is. Wales, Scotland
#: and Northern Ireland are each a genuinely distinct part of the
#: country and keep their points — their centroids sit 3.4°, 2.98° and
#: 3.1° from the UK's, against England's 1.87°.
#:
#: The test is share of the country, not distance from its centre: 24 of
#: 256 regions sit within 1.6° of their country's centroid — Bekaa,
#: Negev, Zurich canton, North Holland — and none of those is a stand-in
#: for its state. In a small country a central region is simply where it
#: is.
#:
#: Excluded here only. These stay in ``geo_terms.json`` and keep working
#: as country evidence: "England beat Australia at Lord's" still resolves
#: GB, it just does not claim to know where that happened.
COUNTRY_SIZED = frozenset({("GB", "england")})

#: Institutions are not regions; they sit in a capital. Pinning the
#: Kremlin on Moscow is more useful than not pinning it at all.
INSTITUTIONS = {
    "whitehall": "London",
    "westminster": "London",
    "pentagon": "Washington, D.C.",
    "white house": "Washington, D.C.",
    "capitol hill": "Washington, D.C.",
    "kremlin": "Moscow",
    "knesset": "Jerusalem",
    "bundestag": "Berlin",
    "elysee": "Paris",
    "dail": "Dublin",
}


def read_dbf(path: Path) -> list[dict[str, str]]:
    """Minimal dBase III/IV reader — Natural Earth's attribute table only.

    32-byte header, 32 bytes per field descriptor, then fixed-width
    records. Values are NUL-padded and hold UTF-8 despite the codepage
    byte. Avoids a shapefile dependency for what is a flat table.
    """
    with path.open("rb") as fh:
        header = fh.read(32)
        n_records, header_len, record_len = struct.unpack("<IHH", header[4:12])
        fields: list[tuple[str, int]] = []
        while True:
            fd = fh.read(32)
            if fd[0:1] == b"\r" or len(fd) < 32:
                break
            fields.append((fd[0:11].split(b"\x00")[0].decode("latin-1"), fd[16]))

        fh.seek(header_len)
        rows: list[dict[str, str]] = []
        for _ in range(n_records):
            raw = fh.read(record_len)
            if len(raw) < record_len:
                break
            if raw[0:1] == b"*":  # deleted record
                continue
            pos, row = 1, {}
            for name, flen in fields:
                cell = raw[pos : pos + flen].split(b"\x00")[0]
                row[name] = cell.decode("utf-8", errors="replace").strip()
                pos += flen
            rows.append(row)
    return rows


def normalise(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").replace(".", "").split())


def strip_suffix(text: str) -> str:
    for suffix in SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def fetch_dbf(target_dir: Path) -> Path:
    archive = target_dir / "ne10.zip"
    print(f"downloading {NE_URL} ...", flush=True)
    urllib.request.urlretrieve(NE_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extract(DBF_NAME, target_dir)
    return target_dir / DBF_NAME


def build_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], tuple[float, float]]:
    """(ISO2, normalised name) → Natural Earth's own label point.

    The table ships ``latitude``/``longitude`` label anchors, so no
    polygon maths is needed — and a label anchor is a better pin than a
    true centroid anyway, since NE places it where a human would write
    the name (inside the landmass, off the mountains).
    """
    index: dict[tuple[str, str], tuple[float, float]] = {}
    for row in rows:
        iso = row.get("iso_a2", "")
        if not iso or len(iso) != 2:
            continue
        try:
            point = (float(row["latitude"]), float(row["longitude"]))
        except (KeyError, ValueError):
            continue
        for column in ("name", "name_en", "name_alt", "gn_name", "woe_name"):
            for part in (row.get(column) or "").split("|"):
                if part.strip():
                    index.setdefault((iso, normalise(part)), point)

    # Constituent countries (England, Scotland, Wales, Northern Ireland)
    # are not admin-1 units — the UK's admin-1 is county level. Average
    # each geounit's counties so "Wales" resolves to mid-Wales.
    members: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        geounit, iso = row.get("geonunit", ""), row.get("iso_a2", "")
        if not geounit or not iso:
            continue
        try:
            members[(iso, normalise(geounit))].append(
                (float(row["latitude"]), float(row["longitude"]))
            )
        except (KeyError, ValueError):
            continue
    for key, points in members.items():
        index.setdefault(
            key,
            (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            ),
        )
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    terms = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    cities = json.loads(CITIES_PATH.read_text(encoding="utf-8"))
    city_points = {}
    for city in cities:
        city_points.setdefault((city["iso"], city["n"].lower()), (city["lat"], city["lon"]))

    with tempfile.TemporaryDirectory() as tmp:
        index = build_index(read_dbf(fetch_dbf(Path(tmp))))

    def lookup(iso: str, region: str) -> tuple[float, float] | None:
        plain = normalise(region)
        for candidate in (
            plain,
            strip_suffix(plain),
            ALIASES.get(plain, ""),
            ALIASES.get(strip_suffix(plain), ""),
        ):
            if candidate and (iso, normalise(candidate)) in index:
                return index[(iso, normalise(candidate))]
        if plain in INSTITUTIONS:
            return city_points.get((iso, INSTITUTIONS[plain].lower()))
        return None

    out: dict[str, dict[str, list[float]]] = {}
    unmatched: list[str] = []
    country_sized: list[str] = []
    for iso, groups in sorted(terms.items()):
        for region in groups.get("regions", []) or []:
            if (iso, normalise(region)) in COUNTRY_SIZED:
                country_sized.append(f"{iso}:{region}")
                continue
            point = lookup(iso, region)
            if point is None:
                unmatched.append(f"{iso}:{region}")
                continue
            out.setdefault(iso, {})[normalise(region)] = [
                round(point[0], 4),
                round(point[1], 4),
            ]

    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    matched = sum(len(v) for v in out.values())
    total = matched + len(unmatched)
    print(f"wrote {args.out}: {matched}/{total} regions ({matched / total:.0%})")
    if country_sized:
        print("held back as country-sized (keep a country, never a pin):")
        print("  " + ", ".join(country_sized))
    if unmatched:
        print("unmatched (these keep a country but no point):")
        print("  " + ", ".join(unmatched))


if __name__ == "__main__":
    main()
