"""ACLED must not build events it is about to discard (#546).

Measured on the real exports: one 12.1 MB file produced 253,172 Event objects
and added 1,054 MB of RSS. Twelve such files accumulated to roughly 3.1 GB —
all of it then filtered down to at most 500 events inside the lookback window.
The containerised worker's ceiling is 1500m, so a fresh export would be
OOM-killed mid-parse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.sources.acled_fetcher import parse_acled_csv

FETCHED_AT = datetime(2026, 7, 20, tzinfo=UTC)

_HEADER = "event_id_cnty,event_date,country,latitude,longitude,fatalities,event_type,notes\n"


def _row(event_id: str, day: str) -> str:
    return f"{event_id},{day},Peru,-12.0,-77.0,1,Battles,note\n"


def test_events_before_the_cutoff_are_never_built():
    body = _HEADER + _row("OLD1", "2020-01-01") + _row("NEW1", "2026-07-19")
    since = FETCHED_AT - timedelta(days=30)
    events = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="t.csv", since=since)
    assert len(events) == 1, "the 2020 row must never be built"
    assert all(e.occurred_at >= since for e in events)


def test_without_a_cutoff_everything_is_parsed():
    """The parameter is optional: existing callers keep their behaviour."""
    body = _HEADER + _row("OLD1", "2020-01-01") + _row("NEW1", "2026-07-19")
    events = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="t.csv")
    assert len(events) == 2


def test_cutoff_keeps_events_exactly_on_the_boundary():
    since = FETCHED_AT - timedelta(days=30)
    on_boundary = since.date().isoformat()
    body = _HEADER + _row("EDGE", on_boundary)
    events = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="t.csv", since=since)
    assert len(events) == 1, "a boundary event is inside the window, not outside it"


def test_rows_with_unparseable_dates_are_kept_not_silently_dropped():
    """A row we cannot date must not vanish because of a filter it never met.

    Dropping it would turn a parsing problem into missing data, which is the
    failure mode this project keeps getting bitten by.
    """
    body = _HEADER + "BAD1,not-a-date,Peru,-12.0,-77.0,1,Battles,note\n"
    since = FETCHED_AT - timedelta(days=30)
    before = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="t.csv")
    after = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="t.csv", since=since)
    assert len(after) == len(before)


def test_excel_sheets_are_read_one_at_a_time(tmp_path):
    """`sheet_name=None` loads every sheet into memory at once (#546).

    Reading them individually means peak memory is the largest sheet rather
    than their sum — the difference between fitting under the worker's
    container ceiling and being OOM-killed mid-parse.
    """
    import pandas as pd

    from app.sources import acled_fetcher as mod

    parsed: list[str] = []
    real_excel_file = pd.ExcelFile

    class SpyExcelFile(real_excel_file):  # type: ignore[misc, valid-type]
        def parse(self, sheet_name=0, **kwargs):
            parsed.append(str(sheet_name))
            return super().parse(sheet_name, **kwargs)

    book = tmp_path / "two_sheets.xlsx"
    with pd.ExcelWriter(book, engine="openpyxl") as writer:
        pd.DataFrame({"event_id_cnty": ["A1"], "event_date": ["2026-07-19"]}).to_excel(
            writer, sheet_name="one", index=False
        )
        pd.DataFrame({"event_id_cnty": ["B1"], "event_date": ["2026-07-19"]}).to_excel(
            writer, sheet_name="two", index=False
        )

    original = mod.pd.ExcelFile
    mod.pd.ExcelFile = SpyExcelFile
    try:
        mod.parse_acled_excel(book, fetched_at=FETCHED_AT, source_name="t.xlsx")
    finally:
        mod.pd.ExcelFile = original

    assert parsed == ["one", "two"], "each sheet must be read on its own"
