"""Tests for `app.sources.gdelt_parser`.

Synthetic GDELT rows so the suite stays hermetic; the live download path is
covered by integration tests in a separate slow suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Category
from app.sources.gdelt_parser import (
    GDELT_COLUMN_COUNT,
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
    # A real export row has 61 columns; sizing the fixture from
    # MIN_FIELD_COUNT is what let the URL sit in the DATEADDED slot (#733).
    fields = [""] * GDELT_COLUMN_COUNT
    fields[0] = global_event_id
    fields[1] = day
    fields[28] = event_root_code
    fields[30] = goldstein
    fields[31] = num_mentions
    fields[34] = avg_tone
    fields[52] = action_country
    fields[56] = action_lat
    fields[57] = action_lon
    fields[59] = "20260618094500"  # DATEADDED
    fields[60] = source_url
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
        event = row_to_event(row, fetched_at=datetime.now(UTC))
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
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_short_row_is_skipped(self) -> None:
        short = ["1"] * 10
        assert row_to_event(short, fetched_at=datetime.now(UTC)) is None

    def test_unparseable_day_is_skipped(self) -> None:
        row = _make_row(day="not-a-date")
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_missing_goldstein_is_skipped(self) -> None:
        row = _make_row(goldstein="")
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_unknown_country_falls_back_to_polygon_lookup(self) -> None:
        # FIPS "ZZ" is not in the table, but Kyiv lat/lon resolves to UA
        # via the polygon fallback.
        row = _make_row(action_country="ZZ")
        event = row_to_event(row, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.country == "UA"
        assert event.payload["country_fips"] == "ZZ"

    def test_unknown_country_with_no_geom_stays_none(self) -> None:
        # FIPS unknown AND no lat/lon → no fallback possible.
        row = _make_row(action_country="ZZ", action_lat="", action_lon="")
        event = row_to_event(row, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.country is None
        assert event.payload["country_fips"] == "ZZ"

    def test_empty_global_id_is_skipped(self) -> None:
        row = _make_row(global_event_id="")
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_invalid_lat_lon_becomes_none(self) -> None:
        row = _make_row(action_lat="", action_lon="not-a-number")
        event = row_to_event(row, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.lat is None
        assert event.lon is None


class TestParseCsvBody:
    def test_empty_body_returns_empty_list(self) -> None:
        assert parse_csv_body("", fetched_at=datetime.now(UTC)) == []

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
        events = parse_csv_body(body, fetched_at=datetime.now(UTC))
        ids = [e.source_event_id for e in events]
        assert ids == ["A", "C"]

    def test_severity_inversion_holds_across_body(self) -> None:
        body = "\n".join(
            [
                "\t".join(_make_row(global_event_id="A", goldstein="-10")),
                "\t".join(_make_row(global_event_id="B", goldstein="5")),
            ]
        )
        events = parse_csv_body(body, fetched_at=datetime.now(UTC))
        assert events[0].severity == 1.0  # most escalatory
        assert events[1].severity == pytest.approx(0.25)  # (10-5)/20


# --- Geo precision (#727) ----------------------------------------------


@pytest.mark.parametrize(
    "geo_type,expected",
    [(3, "city"), (4, "city"), (2, "admin"), (5, "admin"), (1, "country")],
)
def test_geo_type_decides_precision(geo_type: int, expected: str) -> None:
    from app.sources.gdelt_parser import geo_precision

    # The name is deliberately misleading here — the type column wins.
    assert geo_precision(geo_type, "Somewhere, Somewhere, Somewhere") == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Tehran, Tehran, Iran", "city"),
        ("Washington, District of Columbia, United States", "city"),
        ("California, United States", "admin"),
        ("Iran", "country"),
        ("United States", "country"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_name_classifies_rows_stored_before_the_type_was_read(
    name: str | None, expected: str
) -> None:
    from app.sources.gdelt_parser import geo_precision

    assert geo_precision(None, name) == expected


def test_row_carries_geo_precision_and_name() -> None:
    from app.sources.gdelt_parser import row_to_event

    fields = [""] * MIN_FIELD_COUNT
    fields[0] = "1000000002"
    fields[1] = "20260618"
    fields[28] = "18"
    fields[30] = "-8.0"
    fields[31] = "12"
    fields[51] = "4"  # world city
    fields[52] = "Kharkiv, Kharkivs'ka Oblast', Ukraine"
    fields[56] = "50.0"
    fields[57] = "36.25"

    event = row_to_event(fields, fetched_at=datetime.now(UTC))
    assert event is not None
    assert event.payload["geo_precision"] == "city"
    assert event.payload["geo_type"] == 4
    assert event.payload["geo_name"] == "Kharkiv, Kharkivs'ka Oblast', Ukraine"


def test_a_country_level_row_is_marked_as_such() -> None:
    # Its coordinate means "somewhere in Russia" — a real number that is not
    # a real place. The map must be able to tell.
    from app.sources.gdelt_parser import row_to_event

    fields = [""] * MIN_FIELD_COUNT
    fields[0] = "1000000003"
    fields[1] = "20260618"
    fields[28] = "18"
    fields[30] = "-8.0"
    fields[31] = "12"
    fields[51] = "1"  # country
    fields[52] = "Russia"
    fields[56] = "60.0"
    fields[57] = "100.0"

    event = row_to_event(fields, fetched_at=datetime.now(UTC))
    assert event is not None
    assert event.payload["geo_precision"] == "country"


# --- Article URL and action label (#733) --------------------------------


def _geo_row(*, source_url: str | None = "https://example.com/story") -> list[str]:
    """A full 61-column row, the shape GDELT actually publishes."""
    fields = [""] * GDELT_COLUMN_COUNT
    fields[0] = "1000000010"
    fields[1] = "20260618"
    fields[28] = "17"  # COERCE
    fields[30] = "-5.0"
    fields[31] = "3"
    fields[51] = "4"
    fields[52] = "Glasgow, Glasgow City, United Kingdom"
    fields[56] = "55.86"
    fields[57] = "-4.25"
    fields[59] = "20260801094500"  # DATEADDED — what was being read as the URL
    if source_url is not None:
        fields[60] = source_url
    return fields


def test_source_url_is_the_article_not_the_export_timestamp() -> None:
    event = row_to_event(_geo_row(), fetched_at=datetime.now(UTC))
    assert event is not None
    assert event.payload["source_url"] == "https://example.com/story"


def test_a_row_missing_only_its_url_is_still_placed() -> None:
    # MIN_FIELD_COUNT is the geo columns, not the last column, so a short
    # row loses its link rather than the whole event.
    short = _geo_row()[:58]
    event = row_to_event(short, fetched_at=datetime.now(UTC))
    assert event is not None
    assert event.lat == pytest.approx(55.86)
    assert event.payload["source_url"] is None


def test_row_carries_a_human_action_label() -> None:
    event = row_to_event(_geo_row(), fetched_at=datetime.now(UTC))
    assert event is not None
    assert event.payload["action_label"] == "Coerce"


def test_unknown_root_code_gets_no_label_rather_than_a_placeholder() -> None:
    from app.sources.gdelt_cameo import cameo_root_label

    assert cameo_root_label("99") is None
    assert cameo_root_label(None) is None
    assert cameo_root_label("") is None


def test_every_conflict_code_we_ingest_has_a_label() -> None:
    from app.sources.gdelt_cameo import CAMEO_CONFLICT_ROOT_CODES, cameo_root_label

    for code in CAMEO_CONFLICT_ROOT_CODES:
        assert cameo_root_label(code), f"root {code} reaches the map with no label"
