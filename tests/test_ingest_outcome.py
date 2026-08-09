"""One vocabulary for transport, output and persistence states (#848)."""

from __future__ import annotations

import pytest

from app.ingest.outcome import IngestOutcome, classify, terminal


def test_new_rows_are_new_data() -> None:
    result = classify(fetched=5, accepted=4, affected=4, inserted=2, rejected=1)
    assert result.state == "new_data"


def test_accepted_snapshot_without_inserts_is_unchanged() -> None:
    result = classify(fetched=5, accepted=5, affected=5, inserted=0, rejected=0)
    assert result.state == "unchanged"


def test_zero_usable_rows_are_empty_even_when_rows_were_rejected() -> None:
    result = classify(fetched=3, accepted=0, affected=0, inserted=0, rejected=3)
    assert result.state == "empty"
    assert result.rejected == 3


def test_static_revision_hint_distinguishes_unchanged_from_empty() -> None:
    result = classify(
        fetched=0,
        accepted=0,
        affected=0,
        inserted=0,
        rejected=0,
        unchanged_hint=True,
    )
    assert result.state == "unchanged"


def test_impossible_count_relationship_is_rejected() -> None:
    with pytest.raises(ValueError, match="inserted <= affected <= accepted"):
        classify(fetched=1, accepted=1, affected=0, inserted=1, rejected=0)


def test_terminal_states_remain_distinct() -> None:
    assert terminal("misconfigured").state == "misconfigured"
    assert terminal("failed").state == "failed"


def test_failed_terminal_outcome_preserves_measured_fetch_evidence() -> None:
    assert terminal("failed", fetched=3, rejected=1) == IngestOutcome(
        state="failed",
        fetched=3,
        rejected=1,
    )


def test_terminal_outcome_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        terminal("failed", fetched=1, rejected=2)
