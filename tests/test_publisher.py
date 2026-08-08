"""Who published this? (#768)

A GDELT marker showed the machine-coded action "Coerce" and nothing else. The
untitled half of that defect is gone — #810 stopped drawing rows with no
headline at all — but the half that remains is the one a reader actually
needs: every RSS row names an accountable owner, and a GDELT row named
nobody, while carrying the URL that says exactly who.

All 16,128 titled GDELT rows in the last seven days carry a `source_url`, so
this is derivable for every row that reaches a map today.

The publisher is the registrable domain, not a prettified name. A hand-written
domain-to-masthead table is a maintenance trap that goes stale silently, and
"postbulletin.com" is checkable by the reader in a way that "Post Bulletin"
is not.
"""

from __future__ import annotations

from app.publisher import publisher_for


class TestGdelt:
    def _payload(self, url: str | None) -> dict:
        return {"title": "Something happened", "source_url": url}

    def test_the_domain_is_the_publisher(self) -> None:
        assert (
            publisher_for("gdelt", self._payload("https://www.postbulletin.com/news/local/why"))
            == "postbulletin.com"
        )

    def test_a_bare_domain_survives(self) -> None:
        assert publisher_for("gdelt", self._payload("http://imemc.org/article/x")) == "imemc.org"

    def test_mobile_and_amp_prefixes_are_not_the_publisher(self) -> None:
        for url in (
            "https://m.jpost.com/story",
            "https://amp.theguardian.com/world/a",
            "https://www.m.example.co.uk/a",
        ):
            assert not publisher_for("gdelt", self._payload(url)).startswith(("m.", "amp.")), url

    def test_a_real_subdomain_is_kept(self) -> None:
        """`news.stv.tv` and `stv.tv` are different desks and the distinction
        is worth keeping; only the transport prefixes are noise."""
        assert publisher_for("gdelt", self._payload("https://news.stv.tv/east/a")) == "news.stv.tv"

    def test_a_missing_url_names_nobody(self) -> None:
        assert publisher_for("gdelt", self._payload(None)) is None

    def test_rubbish_is_not_a_publisher(self) -> None:
        for url in ("", "not a url", "20260806121500", "://"):
            assert publisher_for("gdelt", self._payload(url)) is None, url

    def test_the_case_is_normalised(self) -> None:
        assert publisher_for("gdelt", self._payload("HTTPS://WWW.BBC.CO.UK/a")) == "bbc.co.uk"


class TestFeeds:
    def test_a_feed_uses_its_registered_name(self) -> None:
        """A feed already declares an accountable owner. Deriving a domain for
        it would be a second, worse answer to a question already answered."""
        assert publisher_for("rss-edinburgh-live", {"title": "x"}) == "Edinburgh Live"
        assert publisher_for("rss-bbc-uk", {"title": "x"}) == "BBC UK"

    def test_an_unknown_feed_slug_names_nobody(self) -> None:
        assert publisher_for("rss-not-registered", {"title": "x"}) is None


class TestSensors:
    def test_an_instrument_has_no_publisher(self) -> None:
        """A quake was not published by anyone. Inventing a publisher for a
        reading would be the same overclaim this issue exists to stop."""
        for source in ("usgs-quake", "nasa-firms", "opensky-adsb", "gdacs"):
            assert publisher_for(source, {"magnitude": 5.1}) is None, source


class TestThroughTheApi:
    """A field nothing serves is a field nobody can show."""

    def test_every_event_carries_a_publisher_field(self, db_session):
        from datetime import UTC, datetime

        from fastapi.testclient import TestClient

        from app.api import app, get_session
        from app.db_models import EventRow

        now = datetime.now(UTC)
        db_session.add_all(
            [
                EventRow(
                    source="gdelt",
                    source_event_id="g1",
                    occurred_at=now,
                    category="geopolitical",
                    keywords=[],
                    payload={"title": "A story", "source_url": "https://www.postbulletin.com/a"},
                ),
                EventRow(
                    source="usgs-quake",
                    source_event_id="q1",
                    occurred_at=now,
                    category="hazard",
                    keywords=[],
                    payload={"magnitude": 5.1},
                ),
            ]
        )
        db_session.commit()
        app.dependency_overrides[get_session] = lambda: db_session
        try:
            rows = {r["source"]: r for r in TestClient(app).get("/events").json()}
        finally:
            app.dependency_overrides.clear()
        assert rows["gdelt"]["publisher"] == "postbulletin.com"
        assert rows["usgs-quake"]["publisher"] is None
