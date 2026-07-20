"""Counting daily per-country volume off raw GDELT export rows (#555)."""

from datetime import date

from app.backtest import gdelt_archive
from app.sources.gdelt_parser import MIN_FIELD_COUNT

FILE_DAY = date(2026, 6, 18)


def _row(
    *,
    day: str = "20260618",
    event_root_code: str = "18",
    num_mentions: str = "12",
    action_country: str = "UP",  # Ukraine in FIPS
    action_lat: str = "50.45",
    action_lon: str = "30.52",
) -> str:
    fields = [""] * MIN_FIELD_COUNT
    fields[0] = "1000000001"
    fields[1] = day
    fields[28] = event_root_code
    fields[30] = "-8.0"
    fields[31] = num_mentions
    fields[52] = action_country
    fields[56] = action_lat
    fields[57] = action_lon
    return "\t".join(fields)


def test_counts_one_row_under_its_country_and_the_file_day():
    counts = gdelt_archive.count_rows(_row(), day=FILE_DAY)
    assert counts == {("UA", FILE_DAY): gdelt_archive.DayCount(events=1, mentions=12)}


def test_sums_rows_sharing_a_country():
    body = "\n".join([_row(num_mentions="3"), _row(num_mentions="4")])
    counts = gdelt_archive.count_rows(body, day=FILE_DAY)
    assert counts[("UA", FILE_DAY)] == gdelt_archive.DayCount(events=2, mentions=7)


def test_separates_countries_within_one_file():
    body = "\n".join(
        [
            _row(),
            _row(action_country="JA", action_lat="35.6", action_lon="139.7"),  # Japan
        ]
    )
    counts = gdelt_archive.count_rows(body, day=FILE_DAY)
    assert set(counts) == {("UA", FILE_DAY), ("JP", FILE_DAY)}


def test_buckets_by_the_file_day_not_the_row_day():
    # Verified against a real export: one 15-minute file carried rows dated a
    # year earlier. Day is when the event happened; the file stamp is when
    # GDELT saw it reported, and coverage timing is what the gate measures.
    body = "\n".join([_row(day="20250415"), _row(day="20260316")])
    counts = gdelt_archive.count_rows(body, day=FILE_DAY)
    assert counts == {("UA", FILE_DAY): gdelt_archive.DayCount(events=2, mentions=24)}


def test_counts_every_cameo_code_not_just_conflict():
    # The live fetcher keeps conflict codes only. Narrative volume is coverage
    # volume — the DOC API series it has to be comparable with counts all
    # articles about a country, so this counts all events.
    counts = gdelt_archive.count_rows(_row(event_root_code="03"), day=FILE_DAY)  # cooperation
    assert counts[("UA", FILE_DAY)].events == 1


def test_falls_back_to_the_polygon_lookup_when_the_country_column_is_unusable():
    # Geocoded-to-a-city rows carry free text where a FIPS code belongs; the
    # live parser recovers the country from the action lat/lon and so must this,
    # or the counts drop a large and non-random share of rows.
    counts = gdelt_archive.count_rows(_row(action_country="Kyiv, Kyiv, Ukraine"), day=FILE_DAY)
    assert counts == {("UA", FILE_DAY): gdelt_archive.DayCount(events=1, mentions=12)}


def test_skips_a_row_with_no_recoverable_country():
    row = _row(action_country="", action_lat="", action_lon="")
    assert gdelt_archive.count_rows(row, day=FILE_DAY) == {}


def test_an_unparseable_row_day_costs_nothing():
    # The row's own Day column is no longer read, so a malformed one is not a
    # reason to drop coverage that did appear in this file.
    counts = gdelt_archive.count_rows(_row(day="not-a-day"), day=FILE_DAY)
    assert counts[("UA", FILE_DAY)].events == 1


def test_skips_short_and_blank_rows():
    body = "\n".join(["", "too\tshort", _row()])
    assert len(gdelt_archive.count_rows(body, day=FILE_DAY)) == 1


def test_missing_mention_count_still_counts_the_event():
    counts = gdelt_archive.count_rows(_row(num_mentions=""), day=FILE_DAY)
    assert counts[("UA", FILE_DAY)] == gdelt_archive.DayCount(events=1, mentions=0)


def test_merge_counts_folds_one_file_into_a_running_total():
    running: dict[tuple[str, date], gdelt_archive.DayCount] = {}
    gdelt_archive.merge_counts(
        running, gdelt_archive.count_rows(_row(num_mentions="5"), day=FILE_DAY)
    )
    gdelt_archive.merge_counts(
        running, gdelt_archive.count_rows(_row(num_mentions="6"), day=FILE_DAY)
    )
    assert running == {("UA", FILE_DAY): gdelt_archive.DayCount(events=2, mentions=11)}
