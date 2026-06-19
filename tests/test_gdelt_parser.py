"""Tests for `app.sources.gdelt_parser`.

Synthetic GDELT rows so the suite stays hermetic; the live download path is
covered by integration tests in a separate slow suite.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Category
from app.sources.gdelt_parser import (
    MIN_FIELD_COUNT,
    _goldstein_to_severity,
    parse_csv_body,
    row_to_event,
)


def _make_row(
    *,
    global_event_id: str = "1000000001",
    day: str = "20260618",
    event_root_code: str = "18",  # ASSAULT
    goldstein: str = "-8.0",
    num_mentions: str = "12",
    avg_tone: str = "-4.5",
    action_country: str = "UP",  # Ukraine in FIPS
    action_lat: str = "50.45",
    action_lon: str = "30.52",
    source_url: str = "https://example.com/a",
) -> list[str]:
    fields = [""] * MIN_FIELD_COUNT
    fields[0] = global_event_id
    fields[1] = day
    fields[28] = event_root_code
    fields[30] = goldstein
    fields[31] = num_mentions
    fields[34] = avg_tone
    fields[52] = action_country
    fields[56] = action_lat
    fields[57] = action_lon
    fields[59] = source_url
    return fields


class TestGoldsteinToSeverity:
    def test_max_escalation_is_one(self) -> None:
        assert _goldstein_to_severity(-10.0) == 1.0

    def test_max_cooperation_is_zero(self) -> None:
        assert _goldstein_to_severity(10.0) == 0.0

    def test_zero_is_midpoint(self) -> None:
        assert _goldstein_to_severity(0.0) == pytest.approx(0.5)

    def test_clamped_below(self) -> None:
        assert _goldstein_to_severity(-20.0) == 1.0

    def test_clamped_above(self) -> None:
        assert _goldstein_to_severity(20.0) == 0.0


class TestRowToEvent:
    def test_conflict_row_converts_to_event(self) -> None:
        row = _make_row()
        event = row_to_event(row, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.source == "gdelt"
        assert event.source_event_id == "1000000001"
        assert event.category == Category.GEOPOLITICAL
        assert event.country == "UA"  # FIPS UP → ISO UA
        assert event.severity == pytest.approx(0.9, abs=1e-6)  # (10 - -8) / 20 = 0.9
        assert event.payload["goldstein"] == -8.0
        assert event.payload["country_fips"] == "UP"
        assert "cameo:18" in event.keywords

    def test_cooperative_root_code_is_skipped(self) -> None:
        row = _make_row(event_root_code="03")  # EXPRESS INTENT TO COOPERATE
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_short_row_is_skipped(self) -> None:
        short = ["1"] * 10
        assert row_to_event(short, fetched_at=datetime.now(timezone.utc)) is None

    def test_unparseable_day_is_skipped(self) -> None:
        row = _make_row(day="not-a-date")
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_missing_goldstein_is_skipped(self) -> None:
        row = _make_row(goldstein="")
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_unknown_country_keeps_event_with_country_none(self) -> None:
        row = _make_row(action_country="ZZ")  # not in FIPS table
        event = row_to_event(row, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.country is None
        assert event.payload["country_fips"] == "ZZ"

    def test_empty_global_id_is_skipped(self) -> None:
        row = _make_row(global_event_id="")
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_invalid_lat_lon_becomes_none(self) -> None:
        row = _make_row(action_lat="", action_lon="not-a-number")
        event = row_to_event(row, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.lat is None
        assert event.lon is None


class TestParseCsvBody:
    def test_empty_body_returns_empty_list(self) -> None:
        assert parse_csv_body("", fetched_at=datetime.now(timezone.utc)) == []

    def test_mixed_rows_filtered(self) -> None:
        body = "\n".join(
            [
                "\t".join(_make_row(global_event_id="A", goldstein="-5")),
                "\t".join(_make_row(global_event_id="B", event_root_code="03")),  # skip
                "\t".join(_make_row(global_event_id="C", goldstein="2")),
                "",  # blank
                "malformed-row",
            ]
        )
        events = parse_csv_body(body, fetched_at=datetime.now(timezone.utc))
        ids = [e.source_event_id for e in events]
        assert ids == ["A", "C"]

    def test_severity_inversion_holds_across_body(self) -> None:
        body = "\n".join(
            [
                "\t".join(_make_row(global_event_id="A", goldstein="-10")),
                "\t".join(_make_row(global_event_id="B", goldstein="5")),
            ]
        )
        events = parse_csv_body(body, fetched_at=datetime.now(timezone.utc))
        assert events[0].severity == 1.0  # most escalatory
        assert events[1].severity == pytest.approx(0.25)  # (10-5)/20
