"""Creating and repairing a `.env` (#957).

Every value in these tests is invented. Nothing here reads the operator's real
file, and the code under test never prints a value in the first place.
"""

from __future__ import annotations

from typing import ClassVar

from scripts.env_setup import (
    CheckReport,
    check,
    is_placeholder,
    main,
    overridden_keys,
    parse_env,
    parse_example,
    required_keys,
    set_value,
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

        #: Fresh from the example, the required password is still blank, so the
        #: check is expected to complain — that is the point of it.
        assert main(["check", "--root", str(tmp_path)]) == 1
        (tmp_path / ".env").write_text(
            "POSTGRES_HOST=localhost\nPOSTGRES_PASSWORD=hunter2\nFEATURE_PATH=/data/x\n"
        )
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

    `PRESENCE_WATCHLIST_PATH=/Users/somebody/watch.json` is the obvious thing to
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
        env = "PRESENCE_WATCHLIST_PATH=/Users/somebody/watch.json\n"
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
            "PRESENCE_WATCHLIST_PATH=/Users/somebody/secret-place/watch.json\n"
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
            "EMDAT_CSV_PATH=/Users/somebody/emdat.csv\n"
            "PRESENCE_WATCHLIST_PATH=/Users/somebody/watch.json\n"
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
        env = "A=1\nPRESENCE_WATCHLIST_PATH=/Users/somebody/watch.json\nB=2\n"
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
        (tmp_path / ".env").write_text("K=/Users/somebody/thing.json\n")
        assert main(["set", "K", "/data/thing.json", "--root", str(tmp_path)]) == 0
        assert parse_env((tmp_path / ".env").read_text())["K"] == "/data/thing.json"

    def test_the_command_needs_both_a_key_and_a_value(self, tmp_path):
        (tmp_path / "env.example").write_text("K=\n")
        assert main(["set", "K", "--root", str(tmp_path)]) == 1
