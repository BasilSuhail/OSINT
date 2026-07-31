"""Rebuild ``app/enrichment/data/cities.json`` from Natural Earth (#723).

The bundled gazetteer held 1,248 cities worldwide — seven of them in the
UK. Since #719 a story with no coordinates gets no dot, so that list was
the ceiling on the map: Leeds, Bristol, Newcastle and Cambridge could
never be pinned however well the country resolved.

This rebuilds it from Natural Earth's 10m populated-places set: 7,342
cities, 57 in the UK, 642 KB committed. Measured over 4,000 stored rows,
city matches go 1,108 -> 1,621.

Run this only to change the gazetteer. The source archive is downloaded
to a temp dir and discarded; the runtime keeps no new dependency.

Usage:
    python -m scripts.build_cities [--out PATH]

Source: Natural Earth 10m Populated Places (simple), public domain.
https://www.naturalearthdata.com/downloads/10m-cultural-vectors/
"""

from __future__ import annotations

import argparse
import json
import struct
import tempfile
import urllib.request
import zipfile
from pathlib import Path

NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places_simple.zip"
DBF_NAME = "ne_10m_populated_places_simple.dbf"

_DATA = Path(__file__).resolve().parent.parent / "app" / "enrichment" / "data"
DEFAULT_OUT = _DATA / "cities.json"

#: City names that are also ordinary English words. ``app.enrichment.city``
#: lowercases before matching, so without this "Sent Man to prison" resolves
#: to Man, Côte d'Ivoire and "Independence Day" to Independence, Missouri.
#:
#: Not guessed from a stopword list — derived by counting how often each
#: candidate name appears as a *lowercase* token across 30,000 stored news
#: rows. A town's name is capitalised in prose; vocabulary is not. Every
#: name below cleared 40 lowercase uses; nothing else in the 7,342 came
#: close, so the cut is sharp rather than arbitrary.
#:
#: Re-derive with:
#:   SELECT title || ' ' || summary FROM events WHERE category = 'news'
#: then count `\b[a-z]{3,}\b` tokens and intersect with the city names.
COMMON_WORD_NAMES = frozenset(
    {
        "Man",  # 628 lowercase uses
        "Young",  # 347
        "Price",  # 282
        "Lead",  # 276
        "Reading",  # 258
        "Same",  # 192
        "Progress",  # 153
        "Alert",  # 130
        "Sale",  # 118
        "Temple",  # 96
        "Alliance",  # 95
        "Split",  # 79
        "Mobile",  # 75
        "Buy",  # 63
        "Van",  # 53
        "Independence",  # 46
        "Guide",  # 46
    }
)


def read_dbf(path: Path) -> list[dict[str, str]]:
    """Minimal dBase III/IV reader. See scripts/build_region_coords.py."""
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
            if raw[0:1] == b"*":
                continue
            pos, row = 1, {}
            for name, flen in fields:
                cell = raw[pos : pos + flen].split(b"\x00")[0]
                row[name] = cell.decode("utf-8", errors="replace").strip()
                pos += flen
            rows.append(row)
    return rows


def fetch_dbf(target_dir: Path) -> Path:
    archive = target_dir / "cities.zip"
    print(f"downloading {NE_URL} ...", flush=True)
    urllib.request.urlretrieve(NE_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extract(DBF_NAME, target_dir)
    return target_dir / DBF_NAME


def build(rows: list[dict[str, str]]) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    skipped: list[str] = []
    for row in rows:
        name = (row.get("name") or "").strip()
        iso = (row.get("iso_a2") or "").strip()
        if not name or len(iso) != 2 or iso.startswith("-"):
            continue
        if name in COMMON_WORD_NAMES:
            skipped.append(f"{name} ({iso})")
            continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            continue
        try:
            pop = int(float(row.get("pop_max") or 0))
        except ValueError:
            pop = 0
        alt: list[str] = []
        ascii_name = (row.get("nameascii") or "").strip()
        if ascii_name and ascii_name != name:
            alt.append(ascii_name)
        out.append(
            {
                "n": name,
                "iso": iso,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "pop": pop,
                "alt": alt,
            }
        )
    # Population-descending, so a name collision resolves to the bigger city
    # when nothing else disambiguates — app.enrichment.city relies on this.
    out.sort(key=lambda c: -c["pop"])
    return out, skipped


def merge_previous(cities: list[dict], previous: list[dict]) -> list[dict]:
    """Union in names the outgoing gazetteer had and this one does not.

    The 50m set this replaces carried spelling variants the 10m "simple"
    set drops — Dnipro, Jalandhar, Visakhapatnam, Ahvaz, Fort Worth. Left
    out, 7 of 4,000 measured rows lost a match they previously had, which
    is a regression however small the count. Merging keeps the strictly
    larger vocabulary: every old name still resolves, plus the ~6,000 new
    ones. Names held back as common words stay held back.
    """
    # Every spelling the new gazetteer can already answer to, primary and
    # alternate alike — app.enrichment.city indexes both.
    known: set[tuple[str, str]] = set()
    for city in cities:
        for spelling in [city["n"], *city.get("alt", [])]:
            known.add((spelling.lower(), city["iso"]))

    added = 0
    for old in previous:
        iso = (old.get("iso") or "").strip()
        if len(iso) != 2:
            continue
        spellings = [
            s.strip() for s in [old.get("n") or "", *(old.get("alt") or [])] if s and s.strip()
        ]
        missing = [s for s in spellings if (s.lower(), iso) not in known]
        # Held-back names must stay held back even when they arrive as an
        # alternate spelling of something else.
        missing = [s for s in missing if s not in COMMON_WORD_NAMES]
        if not missing:
            continue
        cities.append(
            {
                "n": missing[0],
                "iso": iso,
                "lat": old["lat"],
                "lon": old["lon"],
                "pop": int(old.get("pop") or 0),
                "alt": missing[1:],
            }
        )
        for spelling in missing:
            known.add((spelling.lower(), iso))
        added += 1

    if added:
        print(f"kept {added} entr(ies) whose spelling only the previous gazetteer had")
    cities.sort(key=lambda c: -c["pop"])
    return cities


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    previous: list[dict] = []
    if args.out.exists():
        previous = json.loads(args.out.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        cities, skipped = build(read_dbf(fetch_dbf(Path(tmp))))

    cities = merge_previous(cities, previous)

    args.out.write_text(json.dumps(cities, ensure_ascii=False), encoding="utf-8")
    by_gb = sum(1 for c in cities if c["iso"] == "GB")
    print(f"wrote {args.out}: {len(cities):,} cities ({by_gb} in GB)")
    print(f"held back as common words: {len(skipped)} — {', '.join(sorted(skipped))}")


if __name__ == "__main__":
    main()
