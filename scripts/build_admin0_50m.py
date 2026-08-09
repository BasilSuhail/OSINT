"""Build the 50 m Admin-0 boundary file used by the place screen.

Natural Earth publishes 242 country features at 50 m carrying roughly 150
properties each, almost all irrelevant here. Stripping to the three fields the
lookup reads takes the committed file from 3.0 MB to 2.2 MB, and a public
repository should not carry 800 KB of columns nobody opens.

Run from the repository root:

    .venv/bin/python scripts/build_admin0_50m.py

The 110 m file beside it stays where it is. Ingest attributes millions of
points a month into country/month buckets, and the coarse polygons are correct
for that; only the place screen, which names a country in its first line, needs
the finer ones.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)
DEST = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "enrichment"
    / "data"
    / "admin0_countries_50m.geojson"
)
KEEP = ("ISO_A2", "ISO_A2_EH", "NAME")


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=120) as response:
        document = json.load(response)

    features = [
        {
            "type": "Feature",
            "properties": {key: feature["properties"].get(key) for key in KEEP},
            "geometry": feature["geometry"],
        }
        for feature in document["features"]
    ]
    DEST.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"))
    )
    print(f"wrote {len(features)} features to {DEST}")


if __name__ == "__main__":
    main()
