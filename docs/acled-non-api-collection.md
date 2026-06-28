# ACLED Non-API Collection

ACLED API access is not a reliable assumption for this project. The practical
path is to treat myACLED as a download platform, keep downloaded data under the
gitignored `data/` tree, and import only recent rows into Postgres.

## Local Folder

Use:

```text
data/private/acled/
```

Configure:

```env
ACLED_CSV_DIR=./data/private/acled
ACLED_API_ENABLED=false
```

The fetcher reads every `*.csv` in that folder, imports recent rows, and relies
on normal event retention to keep the local DB small.

The importer accepts mixed CSV shapes:

- event-level ACLED exports with IDs, dates, coordinates, event types, actors,
  and fatalities;
- country aggregate files with country/year or country/month/year values, which
  become country-level conflict markers using bundled Natural Earth label
  coordinates.

## Source Links

### Interactive Platforms

These are useful for understanding filters, regions, event types, and available
cuts. They may not expose stable direct CSV links.

- ACLED Explorer: https://acleddata.com/platform/explorer
- CAST Conflict Alert System: https://acleddata.com/platform/cast-conflict-alert-system
- Conflict Exposure Calculator: https://acleddata.com/platform/conflict-exposure-calculator

### Aggregated Metric Pages

These are country/year or country/month aggregate datasets. They are useful for
coarse scoring and trend validation, but they are not event-level map markers.

- Political violence events by country/year: https://acleddata.com/aggregated/number-political-violence-events-country-year
- Political violence events by country/month/year: https://acleddata.com/aggregated/number-political-violence-events-country-month-year
- Demonstration events by country/year: https://acleddata.com/aggregated/number-demonstration-events-country-year
- Reported fatalities by country/year: https://acleddata.com/aggregated/number-reported-fatalities-country-year
- Reported civilian fatalities from direct targeting by country/year: https://acleddata.com/aggregated/number-reported-civilian-fatalities-direct-targeting-country-year
- Events targeting civilians by country/year: https://acleddata.com/aggregated/number-events-targeting-civilians-country-year

### Regional Aggregated Data

These are the first practical candidates for file-based collection. Download
CSV files from these pages into `data/private/acled/`, then run the fetcher.

- Africa: https://acleddata.com/aggregated/aggregated-data-africa
- Asia-Pacific: https://acleddata.com/aggregated/aggregated-data-asia-pacific
- Europe and Central Asia: https://acleddata.com/aggregated/aggregated-data-europe-and-central-asia
- Latin America and Caribbean: https://acleddata.com/aggregated/aggregated-data-latin-america-caribbean
- Middle East: https://acleddata.com/aggregated/aggregated-data-middle-east
- United States and Canada: https://acleddata.com/aggregated/aggregated-data-united-states-canada

## Collection Strategy

1. Prefer event-level CSV exports when available.
2. Save downloaded files into `data/private/acled/`.
3. Import only recent rows for the live dashboard.
4. Keep raw downloaded files out of git.
5. Prune local files after the short retention window while laptop storage is
   constrained.
6. After hard drives are attached, expand retention/backfill.

## Automation Options

### Direct Download

If a page exposes a stable CSV URL, add it to a small sync manifest and fetch it
with `httpx`. This is the cleanest path.

Probe the current ACLED pages with:

```bash
.venv/bin/python scripts/acled_discover.py
```

To save the probe result outside git:

```bash
.venv/bin/python scripts/acled_discover.py --write-manifest data/private/acled/acled-download-candidates.json
```

### Browser-Assisted Download

If downloads require a logged-in myACLED browser session, use a local browser
automation script that reuses local cookies and saves CSVs into
`data/private/acled/`. Do not store ACLED passwords in code.

### Manual Fallback

When pages are dynamic or download links are unstable, manually download the
CSV and drop it into `data/private/acled/`. The importer still handles the file
the same way.

## Current Open Question

Anonymous HTTP probing on 2026-06-29 with `scripts/acled_discover.py` did not
find direct CSV/XLSX/ZIP links in the page HTML. The platform pages returned
200 but exposed no file URLs. Most aggregate pages returned 403 outside a
logged-in browser session; `aggregated-data-asia-pacific` returned 200 but still
did not expose plain download URLs. That means direct `httpx` download
automation is unlikely until we inspect a logged-in page/session.

We still need to inspect the actual downloaded file shape from one regional or
event-level CSV. The importer now handles both event-level and country
aggregate files, but one live sample should still be verified before relying on
a new ACLED page. Once one sample exists in `data/private/acled/`, verify:

- column names for event id, date, event type, fatalities, latitude, longitude,
  and country code;
- whether files contain event-level rows or only aggregate rows;
- whether aggregate files need a separate importer path from event files.
