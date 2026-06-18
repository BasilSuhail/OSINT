"""Tests for `app.sources.gdelt_cameo`."""

from __future__ import annotations

from app.sources.gdelt_cameo import (
    CAMEO_CONFLICT_ROOT_CODES,
    fips_to_iso,
    is_conflict_event,
)


class TestFipsToIso:
    def test_known_codes_map_correctly(self) -> None:
        assert fips_to_iso("US") == "US"
        assert fips_to_iso("UK") == "GB"
        assert fips_to_iso("TU") == "TR"
        assert fips_to_iso("JA") == "JP"
        assert fips_to_iso("GM") == "DE"
        assert fips_to_iso("RS") == "RU"
        assert fips_to_iso("UP") == "UA"
        assert fips_to_iso("CH") == "CN"
        assert fips_to_iso("IZ") == "IQ"

    def test_lowercase_accepted(self) -> None:
        assert fips_to_iso("us") == "US"
        assert fips_to_iso("uk") == "GB"

    def test_unknown_code_returns_none(self) -> None:
        assert fips_to_iso("XX") is None
        assert fips_to_iso("ZZ") is None

    def test_empty_input_returns_none(self) -> None:
        assert fips_to_iso("") is None
        assert fips_to_iso(None) is None


class TestIsConflictEvent:
    def test_conflict_codes_pass(self) -> None:
        for code in CAMEO_CONFLICT_ROOT_CODES:
            assert is_conflict_event(code) is True
            assert is_conflict_event(str(code)) is True

    def test_cooperative_codes_rejected(self) -> None:
        for code in range(1, 14):  # 01-13 = cooperation
            assert is_conflict_event(code) is False

    def test_invalid_input_rejected(self) -> None:
        assert is_conflict_event(None) is False
        assert is_conflict_event("") is False
        assert is_conflict_event("not-a-number") is False

    def test_out_of_range_rejected(self) -> None:
        # CAMEO is 1..20; anything outside is invalid.
        assert is_conflict_event(0) is False
        assert is_conflict_event(99) is False

    def test_root_set_covers_escalation_only(self) -> None:
        # Sanity-check the published set: 14..20 only, nothing lower.
        assert CAMEO_CONFLICT_ROOT_CODES == frozenset({14, 15, 16, 17, 18, 19, 20})
