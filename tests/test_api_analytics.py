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


class TestStoryMembers:
    def test_lists_members_with_owner_and_origin(self, db_session):
        """Cards v3 drilldown (#396): who said what, and how alike."""
        from app.db_models import EventRow

        fresh = _seed_stories(db_session)
        db_session.add(
            EventRow(
                id=1,
                source="rss-bbc-world",
                source_event_id="e1",
                occurred_at=NOW - timedelta(hours=2),
                category="news",
                keywords=[],
                payload={"title": "Earthquake strikes Tokyo"},
            )
        )
        db_session.commit()

        rows = _client(db_session).get(f"/stories/{fresh.id}/members").json()
        assert len(rows) == 1
        member = rows[0]
        assert member["title"] == "Earthquake strikes Tokyo"
        assert member["outlet"] == "BBC World"
        assert member["owner"] == "bbc"
        assert member["origin_country"] == "GB"
        assert member["similarity"] == 1.0

    def test_unknown_story_returns_empty_list(self, db_session):
        assert _client(db_session).get("/stories/999999/members").json() == []


class TestJournalMonthly:
    def test_groups_graded_by_instrument_and_month(self, db_session):
        """Cards v3 (#396): the Brier trend the scoreboard draws as grades mature."""
        base = datetime(2026, 5, 1, tzinfo=UTC)
        for i, (outcome, score) in enumerate([(1, 0.8), (0, 0.4), (None, 0.5)]):
            db_session.add(
                PredictionRow(
                    source="composite",
                    method_version="v1.0",
                    country=f"A{i}",
                    bucket_start=base,
                    horizon_months=1,
                    score=score,
                    outcome=outcome,
                    graded_at=base if outcome is not None else None,
                    payload={},
                )
            )
        db_session.commit()

        rows = _client(db_session).get("/journal/monthly").json()
        (line,) = [r for r in rows if r["source"] == "composite"]
        assert line["month"] == "2026-05-01"
        assert line["issued"] == 3
        assert line["graded"] == 2
        # Brier over the two graded rows: ((0.8-1)^2 + (0.4-0)^2) / 2 = 0.1
        assert abs(line["brier"] - 0.1) < 1e-9

    def test_empty_journal_returns_empty_list(self, db_session):
        assert _client(db_session).get("/journal/monthly").json() == []


class TestDisagreementTop:
    def test_most_contested_stories_with_titles(self, db_session):
        """Briefing card (#398): the most contested telling of the window."""
        from app.db_models import StoryDisagreementRow

        fresh = _seed_stories(db_session)
        db_session.add(
            StoryDisagreementRow(
                story_id=fresh.id,
                divergence=0.885,
                components={"groups": {"GB": 4, "RU": 4}, "n_pairs": 1},
                method_version="disagreement-v1.0",
                computed_at=NOW - timedelta(hours=1),
            )
        )
        db_session.commit()

        (row,) = _client(db_session).get("/disagreement/top").json()
        assert row["title"] == "Earthquake strikes Tokyo"
        assert row["divergence"] == 0.885
        assert row["groups"] == {"GB": 4, "RU": 4}

    def test_empty_returns_empty_list(self, db_session):
        assert _client(db_session).get("/disagreement/top").json() == []


class TestCompositeMovers:
    def test_delta_between_last_two_months_ranked(self, db_session):
        """Briefing card (#398): who moved most since last month, plus global mean."""
        from app.db_models import ScoreRow

        may = datetime(2026, 5, 1, tzinfo=UTC)
        june = datetime(2026, 6, 1, tzinfo=UTC)
        for country, prev, latest in [("AA", 0.2, 0.8), ("BB", 0.5, 0.4), ("CC", 0.5, 0.5)]:
            for bucket, value in [(may, prev), (june, latest)]:
                db_session.add(
                    ScoreRow(
                        country=country,
                        bucket_start=bucket,
                        bucket_length=timedelta(days=31),
                        score_name="composite",
                        score_value=value,
                        components={},
                        method_version="v1.0",
                    )
                )
        db_session.commit()

        body = _client(db_session).get("/composite/movers").json()
        assert body["latest_month"] == "2026-06-01"
        assert abs(body["global_mean"] - (0.8 + 0.4 + 0.5) / 3) < 1e-9
        movers = body["movers"]
        assert movers[0]["country"] == "AA"
        assert abs(movers[0]["delta"] - 0.6) < 1e-9
        assert movers[0]["latest"] == 0.8
        # ranked by |delta|: AA (0.6) then BB (-0.1) then CC (0)
        assert [m["country"] for m in movers[:2]] == ["AA", "BB"]

    def test_empty_scores(self, db_session):
        body = _client(db_session).get("/composite/movers").json()
        assert body == {"latest_month": None, "global_mean": None, "movers": []}


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


class TestCompositeMoversDegeneracy:
    """/composite/movers says when its own numbers carry no information (#589).

    The live composite returns 0.5 for every country because retention deletes
    the history its rolling z-score needs (#586). Rendered without comment, a
    flat index reads as a real measurement.
    """

    def _seed(self, session, values):
        from app.db_models import ScoreRow

        may = datetime(2026, 5, 1, tzinfo=UTC)
        june = datetime(2026, 6, 1, tzinfo=UTC)
        for country, value in values.items():
            for bucket in (may, june):
                session.add(
                    ScoreRow(
                        country=country,
                        bucket_start=bucket,
                        bucket_length=timedelta(days=31),
                        score_name="composite",
                        score_value=value,
                        components={},
                        method_version="v2.0",
                    )
                )
        session.commit()

    def test_a_flat_index_is_reported_as_degenerate(self, db_session):
        self._seed(db_session, {"AA": 0.5, "BB": 0.5, "CC": 0.5})

        body = _client(db_session).get("/composite/movers").json()

        assert body["degenerate"] is not None
        assert "no variance" in body["degenerate"]

    def test_a_varying_index_is_not(self, db_session):
        self._seed(db_session, {"AA": 0.2, "BB": 0.6, "CC": 0.9})

        body = _client(db_session).get("/composite/movers").json()

        assert body["degenerate"] is None

    def test_the_existing_keys_are_untouched(self, db_session):
        """Additive only — no existing consumer may break."""
        self._seed(db_session, {"AA": 0.5, "BB": 0.5})

        body = _client(db_session).get("/composite/movers").json()

        assert set(body) >= {"latest_month", "global_mean", "movers"}
        assert body["global_mean"] == 0.5
