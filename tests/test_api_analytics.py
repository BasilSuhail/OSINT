"""Tests for the analytical-layer endpoints — stories, journal, exports reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_session
from app.db_models import (
    PredictionRow,
    StoryCorroborationRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _seed_stories(session):
    fresh = StoryRow(
        method_version="stories-v1.0",
        title="Earthquake strikes Tokyo",
        first_seen=NOW - timedelta(hours=3),
        last_seen=NOW - timedelta(hours=1),
        member_count=3,
        outlet_count=3,
    )
    stale = StoryRow(
        method_version="stories-v1.0",
        title="Old story from last week",
        first_seen=NOW - timedelta(days=8),
        last_seen=NOW - timedelta(days=7),
        member_count=5,
        outlet_count=5,
    )
    session.add_all([fresh, stale])
    session.flush()
    session.add(StoryMemberRow(event_id=1, story_id=fresh.id, similarity=1.0))
    session.commit()
    return fresh


class TestStoriesTop:
    def test_returns_recent_stories_only(self, db_session):
        _seed_stories(db_session)
        rows = _client(db_session).get("/stories/top").json()
        assert [r["title"] for r in rows] == ["Earthquake strikes Tokyo"]
        assert rows[0]["outlet_count"] == 3
        assert rows[0]["member_count"] == 3

    def test_hours_window_configurable(self, db_session):
        _seed_stories(db_session)
        rows = _client(db_session).get("/stories/top", params={"hours": 24 * 30}).json()
        assert len(rows) == 2

    def test_sorted_by_outlets_then_members(self, db_session):
        _seed_stories(db_session)
        rows = _client(db_session).get("/stories/top", params={"hours": 24 * 30}).json()
        assert rows[0]["outlet_count"] >= rows[1]["outlet_count"]

    def test_empty_table_returns_empty_list(self, db_session):
        assert _client(db_session).get("/stories/top").json() == []

    def test_carries_corroboration_and_sensor_checks(self, db_session):
        """WS-C step 5 (#365): score + evidence trail + verdict map per story."""
        fresh = _seed_stories(db_session)
        db_session.add_all(
            [
                StoryCorroborationRow(
                    story_id=fresh.id,
                    score=0.75,
                    components={"owner_count": 2, "confirmed_claims": 1},
                    method_version="corroboration-v1.0",
                ),
                StorySensorCheckRow(
                    story_id=fresh.id,
                    claim_type="earthquake",
                    verdict="confirmed",
                    matched_event_id=99,
                    evidence={"source": "usgs-quake", "country": "JP"},
                    method_version="sensor-rules-v1.0",
                ),
            ]
        )
        db_session.commit()

        (row,) = _client(db_session).get("/stories/top").json()
        assert row["corroboration"] == 0.75
        assert row["corroboration_components"]["owner_count"] == 2
        assert row["sensor_checks"] == {"earthquake": "confirmed"}

    def test_unscored_story_has_null_corroboration(self, db_session):
        _seed_stories(db_session)
        (row,) = _client(db_session).get("/stories/top").json()
        assert row["corroboration"] is None
        assert row["sensor_checks"] == {}


class TestJournalScoreboard:
    def test_scoreboard_lines(self, db_session):
        db_session.add_all(
            [
                PredictionRow(
                    source="composite",
                    method_version="v1.0",
                    country="SY",
                    bucket_start=NOW,
                    horizon_months=1,
                    score=0.8,
                    outcome=1,
                    graded_at=NOW,
                    payload={},
                ),
                PredictionRow(
                    source="composite",
                    method_version="v1.0",
                    country="US",
                    bucket_start=NOW,
                    horizon_months=1,
                    score=0.2,
                    payload={},
                ),
            ]
        )
        db_session.commit()
        (line,) = _client(db_session).get("/journal/scoreboard").json()
        assert line["issued"] == 2
        assert line["graded"] == 1
        assert line["pending"] == 1

    def test_empty_journal(self, db_session):
        assert _client(db_session).get("/journal/scoreboard").json() == []


class TestExportReports:
    def test_baselines_report_served(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
        exports = tmp_path / "exports"
        exports.mkdir()
        (exports / "baselines-report.json").write_text(json.dumps({"results": [1]}))
        body = _client(db_session).get("/analytics/baselines").json()
        assert body == {"results": [1]}

    def test_coverage_report_served(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
        exports = tmp_path / "exports"
        exports.mkdir()
        (exports / "coverage-bias.json").write_text(json.dumps({"countries": 200}))
        body = _client(db_session).get("/analytics/coverage").json()
        assert body["countries"] == 200

    def test_missing_report_is_404(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setenv("OSINT_DATA_DIR", str(tmp_path))
        resp = _client(db_session).get("/analytics/baselines")
        assert resp.status_code == 404
        assert "make baselines" in resp.json()["detail"]
