"""Roles, the watchlist, and the ledger that says how long something has flown.

The watchlist in these tests is invented. It carries office labels, the way the
real one must, and no name of any person appears in it.
"""

from __future__ import annotations

import json
from typing import ClassVar

import httpx
import pytest

from app.presence import watchlist


@pytest.fixture(autouse=True)
def _clean_ledger():
    watchlist.clear_ledger()
    yield
    watchlist.clear_ledger()


class TestRoles:
    #: Designators taken from a live sample of the military feed rather than
    #: from a list of famous aircraft: what flies is what has to be readable.
    @pytest.mark.parametrize(
        ("code", "role"),
        [
            ("K35R", "tanker"),
            ("KC10", "tanker"),
            ("E3TF", "isr"),
            ("P8", "isr"),
            ("R135", "isr"),
            ("RQ4", "isr"),
            ("F16", "fighter"),
            ("EUFI", "fighter"),
            ("C17", "transport"),
            ("C30J", "transport"),
            ("A400", "transport"),
            ("EC35", "rotorcraft"),
            ("H60", "rotorcraft"),
            ("MI8", "rotorcraft"),
            ("PC21", "trainer"),
            ("TEX2", "trainer"),
        ],
    )
    def test_reads_the_role_off_the_designator(self, code, role):
        assert watchlist.role_for(code) == role

    def test_an_unknown_designator_has_no_role_rather_than_a_guessed_one(self):
        assert watchlist.role_for("ZZZ9") == "other"

    def test_no_designator_is_no_role(self):
        assert watchlist.role_for(None) == "other"
        assert watchlist.role_for("  ") == "other"

    def test_reads_the_designator_however_it_was_cased(self):
        assert watchlist.role_for(" k35r ") == "tanker"


class TestLoading:
    def test_no_path_is_an_empty_watchlist_not_an_error(self):
        assert not watchlist.load_watchlist(None)

    def test_a_path_that_is_not_there_is_an_empty_watchlist(self, tmp_path):
        assert not watchlist.load_watchlist(str(tmp_path / "absent.json"))

    def test_keys_on_hex_and_registration_both_upper_cased(self, tmp_path):
        path = tmp_path / "watch.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "hex": "ae0451",
                        "registration": "82-8000",
                        "label": "state transport",
                        "category": "state",
                    }
                ]
            )
        )
        loaded = watchlist.load_watchlist(str(path))
        assert set(loaded.exact) == {"AE0451", "82-8000"}
        assert loaded.exact["AE0451"].label == "state transport"
        assert loaded.exact["AE0451"].category == "state"
        #: One airframe under two identifiers is one watch, not two.
        assert loaded.size == 1

    #: One bad line in an operator-edited file must not take the layer down.
    def test_a_malformed_entry_is_skipped_and_the_rest_still_loads(self, tmp_path):
        path = tmp_path / "watch.json"
        path.write_text(
            json.dumps(
                [
                    {"label": "no identifier at all", "category": "state"},
                    {"hex": "ae0451", "label": "state transport", "category": "state"},
                    "not an object",
                ]
            )
        )
        loaded = watchlist.load_watchlist(str(path))
        assert set(loaded.exact) == {"AE0451"}

    def test_a_file_that_is_not_json_is_an_empty_watchlist(self, tmp_path):
        path = tmp_path / "watch.json"
        path.write_text("{[}")
        assert not watchlist.load_watchlist(str(path))

    def test_the_shipped_example_carries_no_identifiers_to_mistake_for_real(self):
        entries = watchlist.example_entries()
        assert entries, "the example must show the shape"
        for entry in entries:
            assert entry["label"]
            assert entry["category"] in {"state", "vip", "other"}


class TestMatching:
    WATCH: ClassVar[watchlist.Watchlist] = watchlist.Watchlist(
        exact={
            "AE0451": watchlist.WatchEntry(label="state transport", category="state"),
            "N1234X": watchlist.WatchEntry(label="chartered VIP transport", category="vip"),
        }
    )

    def test_matches_on_hex(self):
        row = {"hex": "ae0451", "registration": None}
        assert watchlist.match(row, self.WATCH).label == "state transport"

    def test_matches_on_registration_when_the_hex_is_not_listed(self):
        row = {"hex": "abcdef", "registration": "n1234x"}
        assert watchlist.match(row, self.WATCH).category == "vip"

    #: The hex is the transponder's own address. The registration is a lookup
    #: the aggregator did, and it is sometimes a guess, so it never overrides.
    def test_the_hex_wins_when_both_are_listed(self):
        row = {"hex": "ae0451", "registration": "n1234x"}
        assert watchlist.match(row, self.WATCH).category == "state"

    def test_no_match_is_none(self):
        assert watchlist.match({"hex": "000000", "registration": None}, self.WATCH) is None

    def test_an_empty_watchlist_matches_nothing(self):
        assert watchlist.match({"hex": "ae0451"}, watchlist.EMPTY_WATCHLIST) is None


class TestRules:
    """Watching a kind of flying rather than one airframe."""

    def _list(self, **fields) -> watchlist.Watchlist:
        return watchlist.load_watchlist_from_entries(
            [{**fields, "label": "a standing interest", "category": "other"}]
        )

    #: The reason rules exist: nobody has thirty hex codes to hand, and the
    #: list would be stale by the next sortie anyway.
    def test_watches_every_aircraft_doing_a_job(self):
        listed = self._list(role="tanker")
        assert watchlist.match({"role": "tanker"}, listed) is not None
        assert watchlist.match({"role": "fighter"}, listed) is None

    #: A callsign is a fleet, not a flight. Matching the whole string would
    #: watch one sortie that has probably already landed.
    def test_watches_a_callsign_as_a_prefix(self):
        listed = self._list(callsign_prefix="RCH")
        assert watchlist.match({"callsign": "RCH411"}, listed) is not None
        assert watchlist.match({"callsign": "rch311"}, listed) is not None
        assert watchlist.match({"callsign": "KING98"}, listed) is None

    def test_watches_a_type_designator(self):
        listed = self._list(type="H47")
        assert watchlist.match({"type": "H47"}, listed) is not None
        assert watchlist.match({"type": "H60"}, listed) is None

    #: Somebody typed the airframe out on purpose; the rule is a standing
    #: interest. The specific one wins.
    def test_a_named_airframe_outranks_a_rule(self):
        listed = watchlist.load_watchlist_from_entries(
            [
                {"hex": "ae0451", "label": "named airframe", "category": "state"},
                {"role": "tanker", "label": "a standing interest", "category": "other"},
            ]
        )
        hit = watchlist.match({"hex": "ae0451", "role": "tanker"}, listed)
        assert hit is not None
        assert hit.label == "named airframe"

    def test_a_row_missing_the_field_a_rule_reads_is_not_a_match(self):
        listed = self._list(callsign_prefix="RCH")
        assert watchlist.match({"callsign": None}, listed) is None
        assert watchlist.match({}, listed) is None

    #: A rule is one watch however many aircraft it catches, and the rail
    #: prints that number.
    def test_a_rule_counts_as_one_watch(self):
        listed = watchlist.load_watchlist_from_entries(
            [
                {"role": "tanker", "label": "refuelling", "category": "other"},
                {"callsign_prefix": "RCH", "label": "airlift", "category": "other"},
            ]
        )
        assert listed.size == 2

    def test_an_entry_with_neither_identifier_nor_rule_is_skipped(self):
        assert not watchlist.load_watchlist_from_entries([{"label": "nothing to match"}])


class TestAirborneLedger:
    def test_remembers_when_something_was_first_seen_flying(self):
        first = watchlist.note_airborne("AE0451", alt_ft=31000.0, now=1000.0)
        again = watchlist.note_airborne("AE0451", alt_ft=33000.0, now=1600.0)
        assert first == again

    #: On the ground is not airborne, and the clock must not start there.
    def test_does_not_start_the_clock_on_the_ground(self):
        assert watchlist.note_airborne("AE0451", alt_ft=None, now=1000.0) is None

    def test_forgets_an_aircraft_that_has_been_gone_a_while(self):
        watchlist.note_airborne("AE0451", alt_ft=31000.0, now=1000.0)
        watchlist.forget_stale(now=1000.0 + watchlist.LEDGER_GRACE_S + 1)
        assert watchlist.note_airborne("AE0451", alt_ft=31000.0, now=9000.0) == 9000.0

    def test_keeps_an_aircraft_that_was_seen_recently(self):
        watchlist.note_airborne("AE0451", alt_ft=31000.0, now=1000.0)
        watchlist.forget_stale(now=1000.0 + watchlist.LEDGER_GRACE_S - 1)
        assert watchlist.note_airborne("AE0451", alt_ft=31000.0, now=2000.0) == 1000.0

    #: The ledger is this process's memory of what it has seen, and nothing
    #: else. Clearing it must leave nothing behind to read.
    def test_clearing_leaves_nothing(self):
        watchlist.note_airborne("AE0451", alt_ft=31000.0, now=1000.0)
        watchlist.clear_ledger()
        assert watchlist.note_airborne("AE0451", alt_ft=31000.0, now=5000.0) == 5000.0


#: The layer end to end: a watched airframe that the military list never
#: carries, reached because the watchlist is asked about directly.
WATCHED_HEX = {
    "ac": [
        {
            "hex": "a1b2c3",
            "flight": "EXEC01  ",
            "r": "N000EX",
            "t": "GLF6",
            "alt_baro": 41000,
            "track": 88.0,
            "lat": 40.1,
            "lon": -74.2,
        }
    ]
}

MIL_ONE = {
    "ac": [
        {
            "hex": "ae6472",
            "flight": "KING98  ",
            "r": "17-5898",
            "t": "K35R",
            "alt_baro": 21000,
            "track": 202.0,
            "lat": 61.0,
            "lon": -149.8,
        }
    ]
}


def _watch_client(*, watched_fails: bool = False) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v2/hex/"):
            if watched_fails:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json=WATCHED_HEX)
        if path.endswith("/v2/mil"):
            return httpx.Response(200, json=MIL_ONE)
        return httpx.Response(200, json={"ac": []})

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def watch_file(tmp_path, monkeypatch):
    path = tmp_path / "watch.json"
    path.write_text(
        json.dumps([{"hex": "a1b2c3", "label": "chartered executive transport", "category": "vip"}])
    )
    monkeypatch.setenv(watchlist.WATCHLIST_PATH_ENV, str(path))
    from app.presence import aircraft

    aircraft.clear_cache()
    yield path
    aircraft.clear_cache()


class TestTheLayer:
    def test_reaches_an_aircraft_the_military_list_never_carries(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client())
        found = {a["hex"]: a for a in answer["aircraft"]}
        assert "a1b2c3" in found
        assert found["a1b2c3"]["watch"] == {
            "label": "chartered executive transport",
            "category": "vip",
        }
        assert found["a1b2c3"]["kind"] == "watched"

    def test_every_row_carries_the_role_its_designator_says(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client())
        roles = {a["hex"]: a["role"] for a in answer["aircraft"]}
        assert roles["ae6472"] == "tanker"
        assert roles["a1b2c3"] == "transport"

    #: A watched aircraft is drawn from what this process has seen, so the
    #: timestamp is only ever there once something has been seen flying.
    def test_a_watched_aircraft_says_when_it_was_first_seen_flying(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client())
        watched = next(a for a in answer["aircraft"] if a["hex"] == "a1b2c3")
        assert watched["airborne_since"] is not None

    def test_routine_traffic_has_no_watch_label_and_no_clock(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client())
        king = next(a for a in answer["aircraft"] if a["hex"] == "ae6472")
        assert king["watch"] is None
        assert king["airborne_since"] is None

    #: The military list is worth more than the watchlist query. Losing four
    #: hundred aircraft because one extra request was refused would be a worse
    #: answer than an incomplete one, and the response says which happened.
    def test_a_refused_watchlist_query_keeps_the_military_list(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client(watched_fails=True))
        assert answer["degraded"] is True
        assert "ae6472" in {a["hex"] for a in answer["aircraft"]}

    def test_no_watchlist_configured_is_a_working_layer(self, monkeypatch):
        from app.presence import aircraft

        monkeypatch.delenv(watchlist.WATCHLIST_PATH_ENV, raising=False)
        aircraft.clear_cache()
        answer = aircraft.live_aircraft(client=_watch_client())
        assert {a["hex"] for a in answer["aircraft"]} == {"ae6472"}
        aircraft.clear_cache()

    #: An empty map has two very different causes and the console has to be
    #: able to tell them apart: nobody is watching anything, or the watched
    #: aircraft are not flying.
    def test_says_how_many_airframes_are_being_watched(self, watch_file):
        from app.presence import aircraft

        answer = aircraft.live_aircraft(client=_watch_client())
        assert answer["watching"] == 1

    def test_says_nobody_is_being_watched_when_no_list_is_configured(self, monkeypatch):
        from app.presence import aircraft

        monkeypatch.delenv(watchlist.WATCHLIST_PATH_ENV, raising=False)
        aircraft.clear_cache()
        answer = aircraft.live_aircraft(client=_watch_client())
        assert answer["watching"] == 0
        aircraft.clear_cache()


class TestProvenance:
    #: The layer draws what the aggregator flagged. That is a claim it made
    #: about an airframe, not a reading of anything the aircraft transmitted,
    #: and the row carries it so the card can say whose claim it is.
    def test_carries_the_source_database_flag(self):
        from app.presence import aircraft

        row = aircraft.normalise(
            {"hex": "896264", "lat": 41.8, "lon": 19.0, "t": "B772", "dbFlags": 1},
            kind="military",
        )
        assert row["source_flags"] == 1

    def test_a_row_with_no_flag_says_nothing_rather_than_zero(self):
        from app.presence import aircraft

        row = aircraft.normalise({"hex": "abc123", "lat": 1.0, "lon": 2.0}, kind="military")
        assert row["source_flags"] is None


class TestTheConventionalPath:
    #: A file dropped at the conventional path needs no variable set. This is
    #: the difference between a feature an operator can try and one they have
    #: to be told how to switch on.
    def test_reads_the_conventional_path_when_nothing_is_configured(self, tmp_path, monkeypatch):
        monkeypatch.delenv(watchlist.WATCHLIST_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        target = tmp_path / watchlist.WATCHLIST_DEFAULT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps([{"role": "tanker", "label": "refuelling"}]))
        assert watchlist.watchlist_from_env().size == 1

    def test_no_file_anywhere_is_still_an_empty_watchlist(self, tmp_path, monkeypatch):
        monkeypatch.delenv(watchlist.WATCHLIST_PATH_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert not watchlist.watchlist_from_env()

    #: A named path is a decision. Falling back after a typo would silently
    #: watch a different list than the one asked for.
    def test_a_configured_path_wins_even_when_it_is_wrong(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        conventional = tmp_path / watchlist.WATCHLIST_DEFAULT_PATH
        conventional.parent.mkdir(parents=True, exist_ok=True)
        conventional.write_text(json.dumps([{"role": "tanker", "label": "refuelling"}]))
        monkeypatch.setenv(watchlist.WATCHLIST_PATH_ENV, str(tmp_path / "typo.json"))
        assert not watchlist.watchlist_from_env()
