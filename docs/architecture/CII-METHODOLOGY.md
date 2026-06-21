# CII v1 — Country Instability Index Methodology

**Status:** v1.0 — first published version, ships in PR closing issue #127.
**Module:** `app.cii.scoring`
**Method version stamp:** `cii.v1.0`

## What this is

A daily, per-country instability index in the OECD/JRC composite-indicator
tradition. Modelled on koala73/worldmonitor's CII v8 algorithm
(`docs/algorithms.mdx` § Country Instability Index), reduced to a v1
fit-for-OSINT scope that runs on the events Basil's pipeline already
ingests.

The score is published alongside the existing `composite` rows in the
`scores` table, under `score_name = "cii_v1"`. As of #140 the composite
chart is hidden from the dashboard UI; CII v1 is the primary trend
signal. Composite rows continue to be written so the two methodologies
remain comparable in ablation analysis — they are simply no longer
rendered side-by-side.

## Formula

```
CII = 0.40 × baseline + 0.60 × event_score
event_score = 0.25 × unrest
            + 0.30 × conflict
            + 0.20 × security
            + 0.25 × information
```

The `event_score` is on a 0–100 scale; the published `total` is divided by
100 so it satisfies the `scores.score_value` `BETWEEN 0 AND 1` constraint.

### Sub-scores

Each sub-score is on a 0–100 scale, log-dampened so a single huge value
doesn't drown the rest of the components.

| Component | Source | Formula sketch |
|---|---|---|
| **Unrest** | RSS news + UK Police rows with `severity ≥ 0.6` (keyword-boosted) | `log_scale(signals × multiplier, ceiling=log1p(60)) × 100` plus `min(30, sqrt(fatalities) × 6)` |
| **Conflict** | GDELT rows with CAMEO `event_root_code ∈ {18, 19, 20}` | `log_scale(events × multiplier, ceiling=log1p(400)) × 100` |
| **Security** | USGS M5+ quakes (6 pts each, capped 60) + GDACS orange/red (12 pts each, capped 60) | `min(100, (quake + hazard) × multiplier)` |
| **Information** | News + UK Police row volume per 24 h | `log_scale(volume × multiplier, ceiling=log1p(300)) × 100` |

`log_scale(raw, ceiling_log)` is `min(100, log1p(raw) / ceiling_log × 100)`.

## Per-country baselines

Each ISO carries two coefficients:

- `baseline ∈ [0, 50]` — structural fragility prior.
- `multiplier ∈ (0, ∞)` — event sensitivity. Values > 1 for fragile / active
  conflict regions; values < 1 for high-volume English-language feeds (US /
  UK) where 200 news rows is a quiet day, not stress.

The v1 seed (Tier-1, n = 12):

| ISO | Baseline | Multiplier | Notes |
|---|---|---|---|
| US | 18 | 0.6 | High volume, low structural risk |
| GB | 14 | 0.65 | Same — UK news volume dominates |
| PK | 42 | 1.15 | Active fragility |
| IN | 24 | 0.95 | Mid-volume, moderate baseline |
| CN | 26 | 0.85 | News access constrained → mid baseline |
| RU | 38 | 1.10 | Sanctions, conflict-adjacent |
| UA | 46 | 1.25 | Active conflict |
| IR | 44 | 1.20 | Persistent escalation risk |
| IL | 40 | 1.15 | Persistent escalation risk |
| SA | 28 | 0.95 | Regional cascade exposure |
| TR | 30 | 1.00 | Mid-fragility |
| BR | 22 | 0.85 | Mid-volume Latin America anchor |

Countries outside the table fall back to `(baseline = 15, multiplier = 1.0)`.

Coefficients are editorial defaults. The methodology version bumps
(`cii.v1.1`, `cii.v2.0`) on any change — never edited in place. Bumping the
version produces a new row alongside the old in the `scores` table, so
historical comparisons stay reproducible.

## Worker schedule

- Cron: every hour at minute 25 (`crontab(hour="*/1", minute=25)`).
- Reads the last 24 h of events (`bucket_end - 24 h`).
- Writes one `scores` row per country in `CII_BASELINES` plus any country
  that had events in the window.
- Idempotent: upsert on `(country, bucket_start, bucket_length, score_name,
  method_version)`.

## Differences vs WorldMonitor's CII v8

| Aspect | WM CII v8 | OSINT CII v1 |
|---|---|---|
| Sub-scores | Unrest / Conflict / Security / Information | Same |
| Top-level blend | 40 / 60 baseline vs event | Same |
| Sub-weights | 25 / 30 / 20 / 25 | Same |
| Tier-1 countries | 31 | 12 (v1 seed) |
| ACLED source | Yes | No — gated by issue #65 |
| OREF / Israel boost | Yes | No — out of v1 scope |
| Advisory floors / UCDP floors | Yes | No — v2 candidate |
| AIS / aviation closure inputs | Yes | No — OSINT doesn't ingest AIS |

## v2 candidate inputs

- ACLED (post-#65 gate close).
- BERT sentiment magnitude from issue #126 — replaces the keyword-bumped
  severity proxy in the Unrest score.
- Advisory floors via the State Department travel advisory feed.
- The remaining 19 WM Tier-1 countries.
- Sub-national / regional buckets (cells from the convergence detector).

## References

- WorldMonitor CII v8: koala73/worldmonitor `docs/algorithms.mdx` § Country
  Instability Index.
- OECD/JRC Handbook on Constructing Composite Indicators (2008).
- Caldara, D., & Iacoviello, M. (2022). Measuring Geopolitical Risk.
  *American Economic Review*, 112(4), 1194–1225.
