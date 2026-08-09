# Notices

## What the licence covers

[`LICENSE.md`](LICENSE.md) covers the code in this repository and nothing else.

It does not cover, and cannot cover, the data this software fetches. Those
feeds belong to the organisations that publish them, each on its own terms.
Nobody here has the right to sub-licence them, so nobody here has granted you
anything over them.

Running this software makes you the one fetching the data. Whatever the
provider requires — registration, an API key, attribution, a commercial
licence, a limit on redistribution — it requires of you, directly, under the
agreement you accept when you take the key. A permissive line in this file
would not change that, which is why there isn't one.

The list below is a pointer, not a legal summary and not legal advice. Terms
change. Read the current ones for any feed you actually enable.

## Feeds this software can fetch

| Source | Fetcher | Where the terms live |
| --- | --- | --- |
| ACLED — armed conflict events | `app/sources/acled_fetcher.py` | <https://acleddata.com/terms-of-use/> |
| GDELT — global news event coding | `app/sources/gdelt_fetcher.py` | <https://www.gdeltproject.org/about.html> |
| EM-DAT — disaster records | `app/sources/emdat_fetcher.py` | <https://www.emdat.be/> |
| FRED — economic series | `app/sources/fred_fetcher.py` | <https://fred.stlouisfed.org/legal/> |
| NASA FIRMS — active fire detections | `app/sources/nasa_firms_fetcher.py` | <https://firms.modaps.eosdis.nasa.gov/> |
| NASA EONET — natural event tracking | `app/sources/eonet_fetcher.py` | <https://eonet.gsfc.nasa.gov/> |
| GDACS — disaster alerts | `app/sources/gdacs_fetcher.py` | <https://www.gdacs.org/> |
| USGS — earthquakes and ShakeMap | `app/sources/usgs_quake_fetcher.py` | <https://earthquake.usgs.gov/> |
| OpenSky Network — aircraft state vectors | `app/sources/opensky_fetcher.py` | <https://opensky-network.org/about/terms-of-use> |
| Polymarket — prediction market prices | `app/sources/polymarket_fetcher.py` | <https://polymarket.com/tos> |
| UK Police — street-level crime | `app/sources/uk_police_fetcher.py` | <https://data.police.uk/about/> |
| abuse.ch — threat intelligence feeds | `app/sources/abuse_ch_fetchers.py` | <https://abuse.ch/> |
| Yahoo Finance, via the `yfinance` package | `app/sources/yfinance_fetcher.py` | Yahoo's terms of service, plus the `yfinance` project's own notes on what that package is |
| News RSS feeds | `app/sources/rss_news_fetcher.py` | Each publisher's own terms; see `app/sources/rss_feeds.json` for the list |

Some of these are open government data and some are not. Several are free for
noncommercial or research use specifically and require a separate agreement for
anything else — which is one of the reasons this code is licensed the way it
is. Do not assume a feed is permissive because its neighbour in the table is.

UK Police data is published under the Open Government Licence v3.0
(<https://nationalarchives.gov.uk/doc/open-government-licence/version/3/>),
which requires attribution.

News feeds are fetched for headline, link, publication time and derived
metadata. Publishers keep copyright in their articles; this software does not
grant you any right to republish them.

## Data bundled in this repository

Files under `app/enrichment/data/` are gazetteer references committed so the
enrichment step runs offline:

| File | Origin | Terms |
| --- | --- | --- |
| `admin0_countries.geojson` | Natural Earth, 110 m Admin-0 countries | Public domain |
| `cities.json` | Natural Earth, 10 m populated places | Public domain |
| `region_coords.json` | Derived from Natural Earth by `scripts/build_region_coords.py` | Public domain |
| `geo_terms.json` | Written for this project — aliases, demonyms and abbreviations Natural Earth does not carry | Covered by `LICENSE.md` |

Natural Earth places its data in the public domain and asks for no
attribution, though it welcomes credit:
<https://www.naturalearthdata.com/about/terms-of-use/>.

## Third-party code

Python and JavaScript dependencies are not vendored here. They are fetched at
install time from PyPI and npm, each under its own licence, and each stays
under it — this repository's licence does not reach them.

## Warranty

There isn't one. See the No Liability section of [`LICENSE.md`](LICENSE.md).
This is a project under development, its outputs have been wrong before and
will be again, and nothing here is fit to be relied on for any decision that
matters.
