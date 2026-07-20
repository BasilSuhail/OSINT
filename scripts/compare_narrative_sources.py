"""Compare archive-derived narrative volume against the DOC API series (#557).

Decides whether #555's archive counts may stand in for the DOC API series the
gate's existing result was measured against, and which of the two archive
measures — summed mentions or coded event rows — tracks it better.

Reports Spearman on the daily series and, more importantly, whether the two
agree on the day the gate would call the narrative spike.

    uv run python scripts/gdelt_archive.py --start 2026-04-20 --end 2026-07-19
    uv run python scripts/compare_narrative_sources.py --start 2026-04-20 --end 2026-07-19

The archive side must already be ingested; this never downloads it. The DOC
side is paced and cached by `app.backtest.narrative`, so a re-run is cheap.
"""

import argparse
from datetime import date, datetime, timedelta

from app.backtest import gdelt_archive, narrative, source_compare
from app.backtest.registry import load_registry
from app.db import session_scope
from app.enrichment.country import country_name
from app.sources.gdelt_cameo import FIPS_TO_ISO


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


#: The same registry the gate runs against, so the comparison covers exactly
#: the countries whose result would change if the source were swapped.
REGISTRY_PATH = "app/backtest/events.yaml"

#: GDELT's location operator takes FIPS, not ISO — JP is "JA".
ISO_TO_FIPS = {iso: fips for fips, iso in FIPS_TO_ISO.items()}


def doc_query(country: str, scope: str) -> str:
    """The DOC query for one country under one scope.

    `sourcecountry` is what the gate uses today: articles *published by* that
    country's outlets, on any subject. The archive counts ActionGeo — events
    *located in* the country, reported by anyone. Those are different
    quantities, and comparing them measures nothing about whether the archive
    can stand in for the DOC series.

    `location` is the like-for-like scope: articles *about* places in that
    country, which is what ActionGeo counts.
    """
    if scope == "location":
        fips = ISO_TO_FIPS.get(country)
        if not fips:
            raise ValueError(f"no FIPS code for ISO {country!r}")
        return f"locationcc:{fips}"
    name = country_name(country)
    if not name:
        raise ValueError(f"no country name for ISO {country!r}")
    return f"sourcecountry:{name.lower()}"


def _registry_countries() -> list[str]:
    events, _ = load_registry(REGISTRY_PATH)
    return sorted({event.country for event in events})


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument(
        "--scope",
        choices=("location", "sourcecountry"),
        default="location",
        help=(
            "which DOC series to compare against. 'location' is like-for-like "
            "with the archive's ActionGeo counts and is the default; "
            "'sourcecountry' reproduces what the gate uses today."
        ),
    )
    args = parser.parse_args()

    days = [
        args.start + timedelta(days=offset) for offset in range((args.end - args.start).days + 1)
    ]
    countries = _registry_countries()
    print(
        f"{len(countries)} countries, {len(days)} days: {args.start} .. {args.end}, "
        f"DOC scope {args.scope}\n",
        flush=True,
    )
    print(
        f"{'country':<8} {'measure':<9} {'spearman':>9} {'doc spike':>12} "
        f"{'archive spike':>14} {'gap':>5}",
        flush=True,
    )

    rows = []
    with session_scope() as session:
        for country in countries:
            try:
                doc_counts = narrative.fetch_daily_volume(
                    country, args.start, args.end, query=doc_query(country, args.scope)
                )
            except (narrative.NarrativeUnavailableError, ValueError) as exc:
                print(f"{country:<8} DOC unavailable: {exc}", flush=True)
                continue

            doc = [float(doc_counts.get(day, 0)) for day in days]
            for measure in ("mentions", "events"):
                try:
                    archive_counts = gdelt_archive.daily_volume(
                        session, country, args.start, args.end, measure=measure
                    )
                except gdelt_archive.ArchiveWindowMissingError as exc:
                    print(f"{country:<8} archive unavailable: {exc}", flush=True)
                    break

                archive = [float(archive_counts.get(day, 0)) for day in days]
                result = source_compare.compare(days, doc, archive)
                rows.append((country, measure, result))
                print(
                    f"{country:<8} {measure:<9} {_fmt(result.spearman):>9} "
                    f"{_fmt(result.doc_spike_day):>12} {_fmt(result.archive_spike_day):>14} "
                    f"{_fmt(result.spike_gap_days):>5}",
                    flush=True,
                )

    _summarize(rows)


def _summarize(rows) -> None:
    print()
    for measure in ("mentions", "events"):
        subset = [r for _, m, r in rows if m == measure]
        if not subset:
            continue
        correlations = [r.spearman for r in subset if r.spearman is not None]
        gaps = [r.spike_gap_days for r in subset if r.spike_gap_days is not None]
        both_spiked = len(gaps)
        agreed = sum(1 for g in gaps if g == 0)
        median_correlation = (
            sorted(correlations)[len(correlations) // 2] if correlations else float("nan")
        )
        print(
            f"{measure}: median spearman {median_correlation:.3f} over {len(correlations)} "
            f"countries; both sources spiked in {both_spiked}; "
            f"same spike day in {agreed}"
            + (f"; median |gap| {sorted(abs(g) for g in gaps)[len(gaps) // 2]}d" if gaps else "")
        )


if __name__ == "__main__":
    main()
