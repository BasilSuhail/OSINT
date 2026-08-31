"""Creating and repairing a `.env` (#957).

Every value in these tests is invented. Nothing here reads the operator's real
file, and the code under test never prints a value in the first place.
"""

from __future__ import annotations

from typing import ClassVar

from scripts.env_setup import (
    CheckReport,
    Machine,
    check,
    detect_machine,
    generate_secret,
    is_placeholder,
    is_small_machine,
    main,
    mismatched_mirrors,
    originate,
    outdated_profile_keys,
    overridden_keys,
    parse_env,
    parse_example,
    required_keys,
    set_value,
    stale_addresses,
    sync,
)

EXAMPLE = """# Copy to .env and fill. Never commit .env.

# Postgres
#
# Pick any strong password; the container stack reads it too.
POSTGRES_HOST=localhost
POSTGRES_PASSWORD=

# A feature added long after the first copy was taken.
FEATURE_PATH=
"""


class TestReadingTheExample:
    def test_carries_the_comment_that_explains_each_key(self):
        blocks = {b.key: b for b in parse_example(EXAMPLE)}
        assert blocks["POSTGRES_PASSWORD"].comments == ()
        assert "long after" in blocks["FEATURE_PATH"].comments[0]

    #: A comment block with a blank line after it is a section heading, not a
    #: note about the next key, and following the key around would be wrong.
    def test_leaves_a_section_heading_where_it_is(self):
        blocks = {b.key: b for b in parse_example(EXAMPLE)}
        assert "Pick any strong password" in blocks["POSTGRES_HOST"].comments[-1]

    def test_reads_a_value_that_is_already_set(self):
        assert parse_env("A=1\n# note\nB=two words\n") == {"A": "1", "B": "two words"}

    #: What a shell would do reading the same file, so the report describes the
    #: value actually in force rather than the first one written.
    def test_a_key_set_twice_reads_as_the_last_one(self):
        assert parse_env("A=1\nA=2\n")["A"] == "2"


class TestSync:
    def test_creates_the_file_when_there_is_none(self):
        rendered, report = sync(EXAMPLE, None)
        assert report.created
        assert set(parse_env(rendered)) == {"POSTGRES_HOST", "POSTGRES_PASSWORD", "FEATURE_PATH"}

    #: The failure this exists for: a key added to the example months after a
    #: copy was taken, silently absent ever since.
    def test_adds_only_what_is_missing(self):
        env = "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=hunter2\n"
        rendered, report = sync(EXAMPLE, env)
        assert report.added == ["FEATURE_PATH"]
        assert "FEATURE_PATH" in parse_env(rendered)

    #: Somebody's answer, possibly a credential. This script has no opinion
    #: about it and must not reformat, reorder or rewrite it.
    def test_never_touches_a_value_that_is_already_set(self):
        env = "POSTGRES_PASSWORD=hunter2\nPOSTGRES_HOST=db.internal\n"
        rendered, _ = sync(EXAMPLE, env)
        assert rendered.startswith(env)
        assert parse_env(rendered)["POSTGRES_HOST"] == "db.internal"
        assert parse_env(rendered)["POSTGRES_PASSWORD"] == "hunter2"

    def test_brings_the_explanation_with_the_key(self):
        rendered, _ = sync(EXAMPLE, "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=x\n")
        assert "long after" in rendered

    #: Safe to run again and again: the second run finds nothing to do.
    def test_a_second_run_changes_nothing(self):
        once, _ = sync(EXAMPLE, "POSTGRES_HOST=localhost\n")
        twice, report = sync(EXAMPLE, once)
        assert twice == once
        assert not report.changed

    def test_a_file_with_no_trailing_newline_does_not_glue_a_key_to_it(self):
        rendered, _ = sync(EXAMPLE, "POSTGRES_HOST=localhost")
        assert "\nFEATURE_PATH=" in rendered
        assert "localhostFEATURE" not in rendered


class TestCheck:
    REQUIRED: ClassVar[set[str]] = {"POSTGRES_PASSWORD"}

    def test_a_complete_file_is_quiet(self):
        env = "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=hunter2\nFEATURE_PATH=/data/x\n"
        assert check(EXAMPLE, env, self.REQUIRED).ok

    def test_no_file_at_all_is_every_key_missing(self):
        report = check(EXAMPLE, None, self.REQUIRED)
        assert set(report.missing) == {"POSTGRES_HOST", "POSTGRES_PASSWORD", "FEATURE_PATH"}

    #: An empty optional key is a choice — most settings have defaults, and
    #: saying so about all of them would drown the two that matter.
    def test_only_the_keys_the_stack_needs_count_as_empty(self):
        env = "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=\nFEATURE_PATH=\n"
        report = check(EXAMPLE, env, self.REQUIRED)
        assert report.required_empty == ["POSTGRES_PASSWORD"]

    #: The typo case. Every setting has a default, so a misspelled key loads as
    #: nothing and the process starts happily doing the wrong thing.
    def test_a_key_the_example_never_heard_of_is_reported(self):
        env = "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=x\nFEATURE_PTH=/tmp/x\nFEATURE_PATH=\n"
        report = check(EXAMPLE, env, self.REQUIRED)
        assert report.unknown == ["FEATURE_PTH"]
        assert not report.ok

    #: `dev-up.sh` writes this one itself. Reporting it would train an
    #: operator to ignore the one report that catches a typo.
    def test_a_key_this_projects_own_scripts_write_is_not_a_typo(self):
        env = "POSTGRES_HOST=x\nPOSTGRES_PASSWORD=y\nFEATURE_PATH=z\nCOMPOSE_PROJECT_NAME=osint\n"
        assert check(EXAMPLE, env, self.REQUIRED).unknown == []

    def test_notices_a_value_somebody_meant_to_come_back_to(self):
        env = "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=changeme\nFEATURE_PATH=\n"
        assert check(EXAMPLE, env, self.REQUIRED).placeholders == ["POSTGRES_PASSWORD"]

    def test_reads_placeholders_however_they_were_quoted_or_cased(self):
        assert is_placeholder('"CHANGEME"')
        assert is_placeholder("  todo  ")
        assert not is_placeholder("a real value")


class TestRequiredKeys:
    #: Required means the container stack interpolates it, which is checkable,
    #: rather than "important", which is an opinion.
    def test_reads_the_keys_the_compose_files_interpolate(self):
        compose = "environment:\n  A: ${POSTGRES_PASSWORD}\n  B: ${API_PORT:-8000}\n"
        assert required_keys([compose]) == {"POSTGRES_PASSWORD", "API_PORT"}

    def test_no_compose_file_means_nothing_is_required(self):
        assert required_keys([]) == set()


class TestTheCommand:
    def test_sync_writes_the_file_and_check_then_passes(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text(EXAMPLE)
        (tmp_path / "docker-compose.yml").write_text("x: ${POSTGRES_PASSWORD}\n")

        assert main(["sync", "--root", str(tmp_path)]) == 0
        assert (tmp_path / ".env").exists()

        #: The required password is no longer blank after a sync — it is
        #: generated (#964) — so a fresh file passes its own check with nothing
        #: typed into it. That is the whole point of the change.
        assert main(["check", "--root", str(tmp_path)]) == 0

        (tmp_path / ".env").write_text(
            "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=hunter2\nFEATURE_PATH=/data/x\n"
        )
        assert main(["check", "--root", str(tmp_path)]) == 0

    #: Origination must stay inside what the example documents. Writing a key
    #: the example has never heard of puts a value in somebody's file that
    #: `check` then reports back to them as a typo.
    def test_originates_no_key_the_example_does_not_document(self, tmp_path):
        (tmp_path / "env.example").write_text(EXAMPLE)
        (tmp_path / "docker-compose.yml").write_text("x: ${POSTGRES_PASSWORD}\n")
        main(["sync", "--root", str(tmp_path)])
        written = set(parse_env((tmp_path / ".env").read_text()))
        assert written == {"POSTGRES_HOST", "POSTGRES_PASSWORD", "FEATURE_PATH"}
        assert main(["check", "--root", str(tmp_path)]) == 0

    #: The whole report is key names and counts. This file holds credentials
    #: and the output goes to a terminal that may be shared or recorded.
    def test_never_prints_a_value(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text(EXAMPLE)
        (tmp_path / "docker-compose.yml").write_text("x: ${POSTGRES_PASSWORD}\n")
        (tmp_path / ".env").write_text(
            "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=hunter2\nSTRAY=topsecret\n"
        )
        main(["check", "--root", str(tmp_path)])
        printed = capsys.readouterr().out
        assert "hunter2" not in printed
        assert "topsecret" not in printed
        assert "STRAY" in printed

    def test_missing_example_is_an_error_not_a_crash(self, tmp_path):
        assert main(["sync", "--root", str(tmp_path)]) == 1


def test_report_knows_when_it_is_happy():
    assert CheckReport().ok


class TestADuplicatedKey:
    #: Found by this script on its first run against the real example: the
    #: same key defined in two places, the second quietly winning.
    DOUBLED: ClassVar[str] = "A=1\n\n# a second opinion\nA=2\nB=3\n"

    def test_reports_a_key_the_example_defines_twice(self):
        report = check(self.DOUBLED, "A=1\nB=3\n", set())
        assert report.duplicated == ["A"]
        assert not report.ok

    #: The example's mistake must not become two lines in somebody's file,
    #: where the second would override the answer they gave.
    def test_appends_a_doubled_key_only_once(self):
        rendered, report = sync(self.DOUBLED, "B=3\n")
        assert report.added == ["A"]
        assert rendered.count("\nA=") == 1

    def test_a_clean_example_reports_nothing_doubled(self):
        assert check(EXAMPLE, "POSTGRES_HOST=x\n", set()).duplicated == []


class TestAPathTheContainerCannotSee:
    """The mistake that cost a live debugging session (#959).

    `PRESENCE_WATCHLIST_PATH=/host/operator/watch.json` is the obvious thing to
    write. The file is right there. It is also nothing at all inside the
    container that reads it, and everything downstream reported an empty
    watchlist rather than a missing file.
    """

    EXAMPLE_WITH_PATHS: ClassVar[str] = (
        "OSINT_DATA_DIR=./data\nPRESENCE_WATCHLIST_PATH=\nACLED_CSV_PATH=\n"
    )
    #: The compose files interpolate this one, so it is read out here on the
    #: host, where an absolute path is exactly right.
    REQUIRED: ClassVar[set[str]] = {"OSINT_DATA_DIR"}

    def test_flags_a_path_from_this_machine(self):
        env = "PRESENCE_WATCHLIST_PATH=/host/operator/watch.json\n"
        report = check(self.EXAMPLE_WITH_PATHS, env, self.REQUIRED)
        assert report.host_paths == ["PRESENCE_WATCHLIST_PATH"]
        assert not report.ok

    def test_accepts_a_path_inside_the_container(self):
        env = "PRESENCE_WATCHLIST_PATH=/data/watchlist.json\n"
        assert check(self.EXAMPLE_WITH_PATHS, env, self.REQUIRED).host_paths == []

    #: A key the compose files interpolate is read on the host by definition,
    #: so an absolute path there is not a mistake.
    def test_leaves_a_host_side_key_alone(self):
        env = "OSINT_DATA_DIR=/Volumes/External/osint\n"
        assert check(self.EXAMPLE_WITH_PATHS, env, self.REQUIRED).host_paths == []

    def test_says_nothing_about_an_empty_key(self):
        env = "PRESENCE_WATCHLIST_PATH=\nACLED_CSV_PATH=\n"
        assert check(self.EXAMPLE_WITH_PATHS, env, self.REQUIRED).host_paths == []

    #: A relative path is resolved by whoever reads it, and this script has no
    #: way to know where that is. Guessing would be noise.
    def test_says_nothing_about_a_relative_path(self):
        env = "PRESENCE_WATCHLIST_PATH=data/watchlist.json\n"
        assert check(self.EXAMPLE_WITH_PATHS, env, self.REQUIRED).host_paths == []

    def test_the_report_names_the_key_and_not_the_path(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text(self.EXAMPLE_WITH_PATHS)
        (tmp_path / "docker-compose.yml").write_text("x: ${OSINT_DATA_DIR}\n")
        (tmp_path / ".env").write_text(
            "OSINT_DATA_DIR=./data\n"
            "PRESENCE_WATCHLIST_PATH=/host/operator/secret-place/watch.json\n"
            "ACLED_CSV_PATH=\n"
        )
        assert main(["check", "--root", str(tmp_path)]) == 1
        printed = capsys.readouterr().out
        assert "PRESENCE_WATCHLIST_PATH" in printed
        assert "secret-place" not in printed

    #: Compose hands some keys to the container outright — `EMDAT_CSV_PATH:
    #: /data/private/emdat.csv`. Whatever `.env` says never reaches the
    #: process, so a host path there cannot be wrong. The first version of
    #: this check reported one, which is exactly the sort of false alarm that
    #: teaches an operator to ignore the report.
    def test_leaves_alone_a_key_the_compose_files_set_outright(self):
        example = "EMDAT_CSV_PATH=\nPRESENCE_WATCHLIST_PATH=\n"
        env = (
            "EMDAT_CSV_PATH=/host/operator/emdat.csv\n"
            "PRESENCE_WATCHLIST_PATH=/host/operator/watch.json\n"
        )
        report = check(example, env, set(), {"EMDAT_CSV_PATH"})
        assert report.host_paths == ["PRESENCE_WATCHLIST_PATH"]


class TestReadingCompose:
    COMPOSE: ClassVar[str] = (
        "services:\n"
        "  api:\n"
        "    environment:\n"
        "      EMDAT_CSV_PATH: /data/private/emdat.csv\n"
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"
        "    ports:\n"
        '      - "${API_PORT:-8000}:8000"\n'
    )

    def test_finds_the_keys_given_a_literal_value(self):
        assert overridden_keys([self.COMPOSE]) == {"EMDAT_CSV_PATH"}

    #: A key whose compose value interpolates `.env` is not overridden — it is
    #: passed through, and `.env` is exactly where it comes from.
    def test_does_not_count_a_passed_through_key_as_overridden(self):
        assert "POSTGRES_PASSWORD" not in overridden_keys([self.COMPOSE])
        assert "POSTGRES_PASSWORD" in required_keys([self.COMPOSE])


class TestSettingOneKey:
    """The one exception to "never touch a value" (#959).

    `sync` is a general tool with no business overwriting somebody's answer.
    This is called by the command that owns a particular setting, to point it
    at the file that command has just written — because a check that reports
    the same broken path twice and fixes nothing is worth nothing.
    """

    def test_points_an_existing_key_somewhere_else(self):
        env = "A=1\nPRESENCE_WATCHLIST_PATH=/host/operator/watch.json\nB=2\n"
        rendered, changed = set_value(env, "PRESENCE_WATCHLIST_PATH", "/data/watchlist.json")
        assert changed
        assert parse_env(rendered)["PRESENCE_WATCHLIST_PATH"] == "/data/watchlist.json"
        assert parse_env(rendered)["A"] == "1"
        assert parse_env(rendered)["B"] == "2"

    def test_adds_the_key_when_it_is_not_there(self):
        rendered, changed = set_value("A=1\n", "PRESENCE_WATCHLIST_PATH", "/data/watchlist.json")
        assert changed
        assert parse_env(rendered)["PRESENCE_WATCHLIST_PATH"] == "/data/watchlist.json"

    #: Running the command twice must not keep rewriting the file.
    def test_says_nothing_changed_when_it_already_points_there(self):
        env = "PRESENCE_WATCHLIST_PATH=/data/watchlist.json\n"
        rendered, changed = set_value(env, "PRESENCE_WATCHLIST_PATH", "/data/watchlist.json")
        assert not changed
        assert rendered.strip() == env.strip()

    #: A key written twice is read as the last one, so an earlier line left
    #: behind is a line that lies about what is in force.
    def test_leaves_no_earlier_line_for_the_same_key(self):
        env = "K=/old/one\nA=1\nK=/older/still\n"
        rendered, _ = set_value(env, "K", "/data/new")
        assert rendered.count("K=") == 1
        assert parse_env(rendered)["K"] == "/data/new"

    def test_keeps_the_comments_around_it(self):
        env = "# why this exists\nK=/old\n# and this\nA=1\n"
        rendered, _ = set_value(env, "K", "/data/new")
        assert "# why this exists" in rendered
        assert "# and this" in rendered

    def test_the_command_writes_it(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text("K=\n")
        (tmp_path / ".env").write_text("K=/host/operator/thing.json\n")
        assert main(["set", "K", "/data/thing.json", "--root", str(tmp_path)]) == 0
        assert parse_env((tmp_path / ".env").read_text())["K"] == "/data/thing.json"

    def test_the_command_needs_both_a_key_and_a_value(self, tmp_path):
        (tmp_path / "env.example").write_text("K=\n")
        assert main(["set", "K", "--root", str(tmp_path)]) == 1


#: A machine with two names besides loopback, so a test can tell "every origin
#: this machine answers to" apart from "whatever was hard-coded".
MACHINE = Machine(hosts=("localhost", "box.local", "192.0.2.7"), api_port=8000, frontend_port=3000)

ORIGIN_EXAMPLE = """POSTGRES_PASSWORD=
API_AUTH_TOKEN=
NEXT_PUBLIC_API_TOKEN=
NEXT_PUBLIC_API_URL=/api
API_CORS_ORIGINS=http://localhost:3000,http://localhost:3001
OSINT_PUBLIC_HOST=
"""


def _fixed_secret() -> str:
    return "generated-secret"


class TestOriginatingSecrets:
    #: The first-run tax this exists to remove: three values, one of which must
    #: equal another, supplied by hand before anything starts (#964).
    def test_fills_a_secret_that_is_empty(self):
        written = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert written["POSTGRES_PASSWORD"] == "generated-secret"
        assert written["API_AUTH_TOKEN"] == "generated-secret"

    #: The promise the script already makes, and the one that matters most
    #: here: a secret it wrote once is somebody's credential from then on.
    def test_never_replaces_a_secret_that_has_a_value(self):
        env = ORIGIN_EXAMPLE.replace("POSTGRES_PASSWORD=", "POSTGRES_PASSWORD=hunter2")
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert "POSTGRES_PASSWORD" not in written

    def test_a_second_run_originates_nothing(self):
        once = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        settled = ORIGIN_EXAMPLE
        for key, value in once.items():
            settled, _ = set_value(settled, key, value)
        assert originate(ORIGIN_EXAMPLE, settled, MACHINE, make_secret=_fixed_secret) == {}

    def test_a_real_secret_is_long_and_not_the_same_twice(self):
        first, second = generate_secret(), generate_secret()
        assert first != second
        assert len(first) >= 32


class TestMirroring:
    #: Two keys that must hold the same string, where a mismatch surfaces as a
    #: blank console rather than as an error.
    def test_the_mirror_takes_the_freshly_generated_source(self):
        written = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert written["NEXT_PUBLIC_API_TOKEN"] == written["API_AUTH_TOKEN"]

    def test_the_mirror_takes_a_source_the_operator_already_set(self):
        env = ORIGIN_EXAMPLE.replace("API_AUTH_TOKEN=", "API_AUTH_TOKEN=theirs")
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert written["NEXT_PUBLIC_API_TOKEN"] == "theirs"
        assert "API_AUTH_TOKEN" not in written

    #: Both answered and disagreeing is a decision, however unlikely to be one
    #: that was meant. Reported by `check`, never overwritten here.
    def test_leaves_a_mirror_that_disagrees_alone(self):
        env = ORIGIN_EXAMPLE.replace("API_AUTH_TOKEN=", "API_AUTH_TOKEN=theirs").replace(
            "NEXT_PUBLIC_API_TOKEN=", "NEXT_PUBLIC_API_TOKEN=different"
        )
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert "NEXT_PUBLIC_API_TOKEN" not in written
        assert mismatched_mirrors(env) == ["NEXT_PUBLIC_API_TOKEN"]

    def test_matching_mirrors_are_not_reported(self):
        env = ORIGIN_EXAMPLE.replace("API_AUTH_TOKEN=", "API_AUTH_TOKEN=same").replace(
            "NEXT_PUBLIC_API_TOKEN=", "NEXT_PUBLIC_API_TOKEN=same"
        )
        assert mismatched_mirrors(env) == []


class TestDerivedAddresses:
    #: One relative route works from loopback, a LAN name, and an HTTPS edge.
    def test_the_api_url_defaults_to_same_origin(self):
        written = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert written.get("NEXT_PUBLIC_API_URL", "/api") == "/api"

    def test_a_pinned_host_does_not_change_the_same_origin_api_route(self):
        env = ORIGIN_EXAMPLE.replace("OSINT_PUBLIC_HOST=", "OSINT_PUBLIC_HOST=box.local")
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert written.get("NEXT_PUBLIC_API_URL", "/api") == "/api"

    def test_migrates_the_former_generated_api_url(self):
        env = ORIGIN_EXAMPLE.replace(
            "NEXT_PUBLIC_API_URL=/api", "NEXT_PUBLIC_API_URL=http://localhost:8000"
        )
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert written["NEXT_PUBLIC_API_URL"] == "/api"

    #: Sharing must never silently narrow what already worked, so the example's
    #: own origins stay in the list rather than being replaced by detection.
    def test_cors_keeps_the_example_origins_and_adds_the_detected_ones(self):
        written = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        #: Stated as the whole list rather than as memberships: the order and
        #: the absence of a second `localhost:3000` are both part of what this
        #: function promises, and a membership check states neither.
        assert written["API_CORS_ORIGINS"].split(",") == [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://box.local:3000",
            "http://192.0.2.7:3000",
        ]

    #: A derived key still holding the example's default is the example's
    #: answer, not the operator's, so deriving over it takes nothing from them.
    def test_treats_the_example_default_as_unanswered(self):
        written = originate(ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert "API_CORS_ORIGINS" in written

    def test_leaves_an_origin_list_the_operator_changed(self):
        env = ORIGIN_EXAMPLE.replace(
            "API_CORS_ORIGINS=http://localhost:3000,http://localhost:3001",
            "API_CORS_ORIGINS=http://only.mine:3000",
        )
        written = originate(ORIGIN_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert "API_CORS_ORIGINS" not in written

    #: `env-refresh` fixes addresses. It must not be able to reach a credential.
    def test_refresh_scope_cannot_touch_a_secret(self):
        written = originate(
            ORIGIN_EXAMPLE, ORIGIN_EXAMPLE, MACHINE, make_secret=_fixed_secret, secrets_too=False
        )
        assert "POSTGRES_PASSWORD" not in written
        assert "API_AUTH_TOKEN" not in written
        assert "NEXT_PUBLIC_API_TOKEN" not in written
        assert "API_CORS_ORIGINS" in written


class TestStaleAddresses:
    def test_the_same_origin_api_route_is_never_stale(self):
        assert stale_addresses(ORIGIN_EXAMPLE, MACHINE) == []

    def test_an_address_this_machine_still_has_is_not_stale(self):
        env = ORIGIN_EXAMPLE.replace(
            "NEXT_PUBLIC_API_URL=/api",
            "NEXT_PUBLIC_API_URL=http://box.local:8000",
        )
        assert stale_addresses(env, MACHINE) == []

    #: The failure it replaces: a console that is blank, with nothing anywhere
    #: saying the address compiled into it belongs to a different network.
    def test_an_address_this_machine_no_longer_has_is_stale(self):
        env = ORIGIN_EXAMPLE.replace(
            "NEXT_PUBLIC_API_URL=/api",
            "NEXT_PUBLIC_API_URL=http://198.51.100.4:8000",
        )
        assert stale_addresses(env, MACHINE) == ["NEXT_PUBLIC_API_URL"]

    #: A pinned host is a decision. Detection does not get to call it wrong.
    def test_a_pinned_host_is_never_stale(self):
        env = ORIGIN_EXAMPLE.replace(
            "NEXT_PUBLIC_API_URL=/api",
            "NEXT_PUBLIC_API_URL=http://198.51.100.4:8000",
        ).replace("OSINT_PUBLIC_HOST=", "OSINT_PUBLIC_HOST=198.51.100.4")
        assert stale_addresses(env, MACHINE) == []


class TestDetection:
    #: Loopback is the fallback that always works, so it is always offered.
    def test_always_offers_loopback(self):
        assert "localhost" in detect_machine().hosts

    def test_offers_each_host_once(self):
        hosts = detect_machine().hosts
        assert len(hosts) == len(set(hosts))


class TestTheCommandOriginates:
    def test_a_first_run_leaves_nothing_to_fill_in(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text(ORIGIN_EXAMPLE)
        assert main(["sync", "--root", str(tmp_path)]) == 0
        written = parse_env((tmp_path / ".env").read_text())
        assert written["POSTGRES_PASSWORD"]
        assert written["API_AUTH_TOKEN"] == written["NEXT_PUBLIC_API_TOKEN"]

    #: The file holds credentials and this output goes to a terminal that may be
    #: shared, logged or recorded. The report names keys and counts, nothing else.
    def test_prints_no_value_it_generated(self, tmp_path, capsys):
        (tmp_path / "env.example").write_text(ORIGIN_EXAMPLE)
        main(["sync", "--root", str(tmp_path)])
        printed = capsys.readouterr().out
        written = parse_env((tmp_path / ".env").read_text())
        assert written["API_AUTH_TOKEN"] not in printed
        assert written["POSTGRES_PASSWORD"] not in printed
        assert "API_AUTH_TOKEN" in printed

    def test_a_second_run_leaves_the_file_byte_identical(self, tmp_path):
        (tmp_path / "env.example").write_text(ORIGIN_EXAMPLE)
        main(["sync", "--root", str(tmp_path)])
        once = (tmp_path / ".env").read_text()
        main(["sync", "--root", str(tmp_path)])
        assert (tmp_path / ".env").read_text() == once

    def test_refresh_updates_addresses_and_leaves_secrets_alone(self, tmp_path):
        (tmp_path / "env.example").write_text(ORIGIN_EXAMPLE)
        main(["sync", "--root", str(tmp_path)])
        before = parse_env((tmp_path / ".env").read_text())
        stale, _ = set_value(
            (tmp_path / ".env").read_text(), "NEXT_PUBLIC_API_URL", "http://198.51.100.4:8000"
        )
        (tmp_path / ".env").write_text(stale)
        assert main(["refresh", "--root", str(tmp_path)]) == 0
        after = parse_env((tmp_path / ".env").read_text())
        assert after["API_AUTH_TOKEN"] == before["API_AUTH_TOKEN"]
        assert after["POSTGRES_PASSWORD"] == before["POSTGRES_PASSWORD"]
        assert after["NEXT_PUBLIC_API_URL"] == "/api"


HOST_ID_EXAMPLE = """POSTGRES_PASSWORD=
API_AUTH_TOKEN=
NEXT_PUBLIC_API_TOKEN=
NEXT_PUBLIC_API_URL=/api
API_CORS_ORIGINS=http://localhost:3000,http://localhost:3001
OSINT_PUBLIC_HOST=
DOCKER_UID=
DOCKER_GID=
"""


class TestWhoTheContainersRunAs:
    """A Linux bind mount keeps the host's ownership (#984).

    A container running as the image's own user cannot then write to a data
    directory belonging to the operator, and the story export fails with
    "Permission denied". Docker Desktop fakes the ownership, so the same stack
    on macOS never asks the question.
    """

    def test_linux_gets_the_running_account(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        written = originate(HOST_ID_EXAMPLE, HOST_ID_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert written["DOCKER_UID"].isdigit()
        assert written["DOCKER_GID"].isdigit()

    #: 501 on macOS names a real account. Writing it into a file that may be
    #: copied to another machine is how a confusing failure travels.
    def test_other_platforms_are_left_empty(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "darwin")
        written = originate(HOST_ID_EXAMPLE, HOST_ID_EXAMPLE, MACHINE, make_secret=_fixed_secret)
        assert "DOCKER_UID" not in written
        assert "DOCKER_GID" not in written

    def test_an_id_the_operator_set_is_never_replaced(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        env = HOST_ID_EXAMPLE.replace("DOCKER_UID=", "DOCKER_UID=4242")
        written = originate(HOST_ID_EXAMPLE, env, MACHINE, make_secret=_fixed_secret)
        assert "DOCKER_UID" not in written

    #: An account id is a fact about this machine, not an address that drifts.
    def test_refresh_cannot_rewrite_it(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        written = originate(
            HOST_ID_EXAMPLE,
            HOST_ID_EXAMPLE,
            MACHINE,
            make_secret=_fixed_secret,
            secrets_too=False,
            rederive=True,
        )
        assert "DOCKER_UID" not in written

    def test_a_key_the_example_omits_is_not_invented(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        without = HOST_ID_EXAMPLE.replace("DOCKER_UID=\nDOCKER_GID=\n", "")
        written = originate(without, without, MACHINE, make_secret=_fixed_secret)
        assert "DOCKER_UID" not in written


#: The model settings only, with the laptop values the real example ships. The
#: small-machine profile has to be able to write over exactly these, because
#: `sync` copies them into `.env` before anything asks whose answer they are.
#:
#: The two question keys ship empty, exactly as the real example does, and for
#: the reason the tests below turn on: empty is on for both the API and the
#: console, so a laptop is unaffected, while a `true` typed into the file is
#: unmistakably somebody's answer rather than a copy of the example's own.
PROFILE_EXAMPLE = """ASK_ENABLED=
NEXT_PUBLIC_ASK_ENABLED=
BRAIN_MODEL=llama3.2:3b
QA_MODEL=qwen3.5:4b-q4_K_M
SEVERITY_MODEL=qwen3.5:4b-q4_K_M
OLLAMA_MODEL=qwen3.5:4b-q4_K_M
BRAIN_KEEP_ALIVE=30m
QA_KEEP_ALIVE=0
BRAIN_MIN_FREE_MB=3500
QA_MIN_FREE_MB=3800
BRAIN_TIMEOUT_S=120
QA_STORIES=6
"""


class TestSizingTheMachine:
    def test_a_board_sized_machine_is_small(self):
        assert is_small_machine(7900)

    #: Sold as 8 GB, reports under it. A threshold of exactly 8 GB would miss
    #: the machine the profile was written for.
    def test_an_eight_gigabyte_board_is_small(self):
        assert is_small_machine(8192)

    def test_a_laptop_is_not(self):
        assert not is_small_machine(16384)

    #: Unreadable must not reconfigure anybody. 0 is below every threshold, so
    #: the test is that it does not read as the smallest machine of all.
    def test_a_machine_that_will_not_say_keeps_the_defaults(self):
        assert not is_small_machine(0)


class TestTheSmallMachineProfile:
    #: What ends up in force, not what happened to be rewritten. The summary
    #: model the example already names is the model the profile wants, so that
    #: key is correctly left alone — and one job silently keeping a 4b would put
    #: two models back in memory, which is the fault this profile exists for.
    def test_every_job_ends_up_on_the_same_model(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        shipped = parse_env(PROFILE_EXAMPLE)
        keys = ("BRAIN_MODEL", "QA_MODEL", "SEVERITY_MODEL", "OLLAMA_MODEL")
        assert len({written.get(k, shipped[k]) for k in keys}) == 1

    #: The floors do NOT come down, which was the first version of this profile
    #: and was wrong. What makes one model affordable on a small board is that
    #: only one is ever resident, not that the guard was lowered — and a 3b needs
    #: about the room a 4b needs. Lowering the floor to fit a 1b was how a model
    #: that fabricates got waved through.
    def test_the_memory_floor_still_protects_the_board(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        floors = {**{k: v for k, v in [("QA_MIN_FREE_MB", "3800"), ("BRAIN_MIN_FREE_MB", "3500")]}}
        for key, shipped in floors.items():
            assert int(written.get(key, shipped)) >= 3500

    #: One model doing every job is the whole mechanism. Two resident at once is
    #: what locked the board up; a weaker model was never the fix.
    def test_the_model_is_capable_rather_than_merely_small(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["QA_MODEL"] == "llama3.2:3b"
        assert "1b" not in written["QA_MODEL"]

    #: Measured at 1 m 48 s an ask on the board. A 120 s ceiling fails it, and
    #: the failure reaches the console as "the brain is offline".
    def test_the_wait_outlasts_a_measured_ask(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert float(written["BRAIN_TIMEOUT_S"]) > 108

    #: Evicting after every answer makes each question pay a cold load first.
    def test_the_model_is_held_between_questions(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["QA_KEEP_ALIVE"] != "0"

    #: The prompt, not the model, is most of an answer's cost on a machine with
    #: no GPU. Sending fewer stories is the cheaper trade than a weaker model.
    def test_it_sends_fewer_stories_to_the_model(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert int(written["QA_STORIES"]) < 6

    def test_a_big_machine_keeps_every_default(self):
        assert originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=False) == {}

    #: The whole reason the profile needs its own exemption: by the time this
    #: runs on a fresh clone, `sync` has already put the laptop values in.
    def test_it_writes_over_the_examples_own_answer(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["QA_MODEL"] != "qwen3.5:4b-q4_K_M"

    #: And the line it must not cross. A value that is not the example's own is
    #: somebody's choice, on any size of machine.
    def test_it_leaves_an_answer_somebody_gave(self):
        env = PROFILE_EXAMPLE.replace("QA_MODEL=qwen3.5:4b-q4_K_M", "QA_MODEL=theirs:7b")
        written = originate(PROFILE_EXAMPLE, env, MACHINE, small=True)
        assert "QA_MODEL" not in written

    def test_a_second_run_writes_nothing_new(self):
        settled = PROFILE_EXAMPLE
        for key, value in originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True).items():
            settled, _ = set_value(settled, key, value)
        assert originate(PROFILE_EXAMPLE, settled, MACHINE, small=True) == {}

    #: `refresh` exists to rewrite addresses. A model setting is not an address,
    #: and must not change on its way past.
    def test_refresh_does_not_touch_a_model(self):
        written = originate(
            PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True, secrets_too=False, rederive=True
        )
        assert written == {}

    #: Never a key the example has not heard of — `check` would report it back
    #: to the operator as a typo.
    def test_it_writes_nothing_the_example_does_not_document(self):
        written = originate(
            "QA_MODEL=qwen3.5:4b-q4_K_M\n", "QA_MODEL=qwen3.5:4b-q4_K_M\n", MACHINE, small=True
        )
        assert set(written) == {"QA_MODEL"}

    #: The build this profile now describes. Everything else the board does is
    #: cheap; a typed question is minutes of a box that has other work, so the
    #: profile removes that one control rather than tuning it.
    def test_a_small_board_gets_the_build_without_the_question_box(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["ASK_ENABLED"] == "false"

    #: Both halves, because the dashboard is a separate process with its own
    #: build-time environment. One of the two alone is a console drawing a
    #: button for an endpoint that refuses, or hiding one that works. The
    #: profile names only the API key; the console's copy follows because it is
    #: a mirror, which is also what lets `check` report the two drifting apart.
    def test_the_dashboard_is_told_the_same_thing(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["NEXT_PUBLIC_ASK_ENABLED"] == written["ASK_ENABLED"]

    #: The mirror has to be taken after the profile has spoken, not before. Read
    #: too early it copies what `.env` said a moment ago — `true` on the board
    #: that has just turned answering off — and the console compiles in an ask
    #: control for an endpoint that refuses.
    def test_the_dashboard_is_told_what_this_run_decided(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["NEXT_PUBLIC_ASK_ENABLED"] == "false"

    #: A laptop keeps the console it has.
    def test_a_big_machine_keeps_the_question_box(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=False)
        assert "ASK_ENABLED" not in written

    #: The line the profile must not cross, for this key like every other: an
    #: operator who wants questions answered on a board has said so, and a
    #: re-sync is not the place to disagree.
    #:
    #: `true` is the word, because `true` is what somebody reading the README
    #: types. The earlier version of this test used a synonym, and passed for
    #: the wrong reason: while the example itself said `true`, the operator's
    #: `true` was indistinguishable from the example's own and was written over
    #: on the next run. Empty in the example is what makes this the real case.
    def test_it_leaves_the_question_box_on_where_somebody_turned_it_on(self):
        env, _ = set_value(PROFILE_EXAMPLE, "ASK_ENABLED", "true")
        written = originate(PROFILE_EXAMPLE, env, MACHINE, small=True)
        assert "ASK_ENABLED" not in written

    #: And it stays turned on. One re-sync proving nothing is the failure this
    #: replaced: the operator's answer has to survive `make env` run again, and
    #: again, which is what "leaves your answer alone from then on" promises.
    def test_the_answer_survives_every_resync(self):
        settled, _ = set_value(PROFILE_EXAMPLE, "ASK_ENABLED", "true")
        for _ in range(3):
            for key, value in originate(PROFILE_EXAMPLE, settled, MACHINE, small=True).items():
                settled, _ = set_value(settled, key, value)
        assert parse_env(settled)["ASK_ENABLED"] == "true"


class TestTheExampleAgreesWithTheCode:
    """`env.example` now writes the model defaults out, and `app/settings.py`
    holds its own copies. Two spellings of one number drift, and the drift is
    silent: whichever is wrong only shows up as a machine behaving unlike the
    documentation somebody read."""

    #: Keys where the example's value must be the code's default. Not every key
    #: — an address is derived per machine and a secret is generated, so those
    #: deliberately differ.
    MIRRORS: ClassVar[dict[str, str]] = {
        "BRAIN_MODEL": "brain_model",
        "QA_MODEL": "qa_model",
        "SEVERITY_MODEL": "severity_model",
        "OLLAMA_MODEL": "ollama_model",
        "BRAIN_KEEP_ALIVE": "brain_keep_alive",
        "QA_KEEP_ALIVE": "qa_keep_alive",
        "BRAIN_MIN_FREE_MB": "brain_min_free_mb",
        "QA_MIN_FREE_MB": "qa_min_free_mb",
        "BRAIN_TIMEOUT_S": "brain_timeout_s",
        "QA_STORIES": "qa_stories",
    }

    def test_each_documented_default_is_the_code_default(self) -> None:
        from pathlib import Path

        from app.settings import Settings

        example = parse_env((Path(__file__).resolve().parents[1] / "env.example").read_text())
        fields = Settings.model_fields
        for key, field_name in self.MIRRORS.items():
            assert key in example, f"{key} is missing from env.example"
            field = fields[field_name]
            #: Through the declared type, not as text: a float default reads
            #: "120.0" while the file sensibly says "120", and that is agreement.
            documented = field.annotation(example[key].strip())
            assert documented == field.default, (
                f"env.example says {key}={example[key].strip()}, settings.py says {field.default}"
            )


class TestUpdatingWhatThisScriptItselfWrote:
    """A board set up while the profile named a 1b kept that 1b for good.

    `make env` read it as a deliberate choice and declined to interfere, which is
    the right instinct about somebody's answer and the wrong one about its own.
    The 1b was found to fabricate — a magnitude, a death toll and two agencies
    that appeared in no retrieved story — so the install stayed broken with
    nothing anywhere saying so.
    """

    #: The exact file `make env` produced when the profile named a 1b.
    def _earlier_version(self) -> str:
        env = PROFILE_EXAMPLE
        for key, value in (
            ("BRAIN_MODEL", "llama3.2:1b"),
            ("QA_MODEL", "llama3.2:1b"),
            ("SEVERITY_MODEL", "llama3.2:1b"),
            ("OLLAMA_MODEL", "llama3.2:1b"),
            ("QA_MIN_FREE_MB", "2000"),
            ("BRAIN_MIN_FREE_MB", "1800"),
        ):
            env, _ = set_value(env, key, value)
        return env

    def test_the_superseded_models_are_replaced(self):
        written = originate(PROFILE_EXAMPLE, self._earlier_version(), MACHINE, small=True)
        assert written["QA_MODEL"] == "llama3.2:3b"
        assert written["BRAIN_MODEL"] == "llama3.2:3b"

    #: Lowered to admit the 1b, which is how a model that invents evidence got
    #: past a guard sized for something bigger.
    def test_the_lowered_floors_are_raised_back(self):
        written = originate(PROFILE_EXAMPLE, self._earlier_version(), MACHINE, small=True)
        assert int(written["QA_MIN_FREE_MB"]) >= 3500

    #: The line this must not cross. A value that is not one of ours is somebody's.
    def test_a_deliberate_choice_is_left_alone(self):
        env, _ = set_value(self._earlier_version(), "QA_MODEL", "mistral:7b")
        written = originate(PROFILE_EXAMPLE, env, MACHINE, small=True)
        assert "QA_MODEL" not in written

    def test_a_current_file_is_not_touched(self):
        settled = PROFILE_EXAMPLE
        for key, value in originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True).items():
            settled, _ = set_value(settled, key, value)
        assert originate(PROFILE_EXAMPLE, settled, MACHINE, small=True) == {}

    #: Reported rather than done quietly: it is the one case here that replaces
    #: something already in the file, and silence would be indistinguishable from
    #: the script overruling an operator.
    def test_the_outdated_keys_can_be_named_before_they_change(self):
        assert set(outdated_profile_keys(self._earlier_version(), small=True)) == {
            "BRAIN_MODEL",
            "QA_MODEL",
            "SEVERITY_MODEL",
            "OLLAMA_MODEL",
            "QA_MIN_FREE_MB",
            "BRAIN_MIN_FREE_MB",
        }

    def test_a_big_machine_has_none_to_update(self):
        assert outdated_profile_keys(self._earlier_version(), small=False) == []
