"""The console's service unit, checked on what it renders.

systemd is not this project's to verify — the daemon is the operating
system's. What is this project's is the text handed to it, and every failure
worth catching here is a failure of that text: a unit that starts before the
address it binds exists, one that does not come back after a crash, one that
writes a secret into a file the whole machine can read.
"""

from __future__ import annotations

import pytest

from app.devx.console_unit import UNIT_NAME, env_file_text, unit_text

ENV = {
    "API_BIND": "100.100.100.100",
    "NEXT_PUBLIC_API_URL": "http://board.example-tailnet.ts.net:8000",
    "NEXT_PUBLIC_API_TOKEN": "a-token",
}


def _unit() -> str:
    return unit_text(
        working_dir="/home/board/OSINT/osint-frontend",
        env_file="/etc/osint-console.env",
        bind="100.100.100.100",
        port=3000,
        commit_file="/home/board/OSINT/osint-frontend/.next/BUILD_COMMIT",
    )


def test_the_unit_is_named_for_what_it_runs() -> None:
    assert UNIT_NAME == "osint-console.service"


#: The bind address does not exist until the tailnet is up. Starting before
#: that is the one failure that happens at boot and not when tried by hand,
#: which is the hardest kind to find. `After=` alone only orders two units
#: that are already starting — it takes `Wants=` to pull tailscaled into the
#: boot transaction at all.
def test_it_waits_for_the_network_and_the_tailnet() -> None:
    unit = _unit()
    assert "After=network-online.target tailscaled.service" in unit
    assert "Wants=network-online.target" in unit
    assert "Wants=network-online.target tailscaled.service" in unit


#: systemd units start with a minimal built-in PATH and never source a login
#: shell, so `pnpm` on an inherited PATH is not guaranteed — the failure mode
#: is a restart loop that logs `status=127` and never says why.
def test_it_does_not_rely_on_an_inherited_path() -> None:
    unit = _unit()
    assert "Environment=PATH=" in unit
    assert "/usr/bin" in unit
    assert "/usr/local/bin" in unit


def test_it_comes_back_after_a_crash() -> None:
    assert "Restart=always" in _unit()


def test_it_starts_the_built_console_on_the_bind_it_was_given() -> None:
    unit = _unit()
    assert "next start" in unit
    assert "-H 100.100.100.100" in unit
    assert "-p 3000" in unit


def test_it_runs_from_the_console_directory() -> None:
    assert "WorkingDirectory=/home/board/OSINT/osint-frontend" in _unit()


#: A stale build is otherwise invisible: the console loads, and the fix that
#: was pulled an hour ago is simply not in it.
def test_it_says_which_build_it_is_serving() -> None:
    assert "BUILD_COMMIT" in _unit()


#: `unit_text` has no parameter that could receive a secret, so this assertion
#: cannot fail whatever the function does — it is not a regression guard.
#: What it records is the interface property that keeps a secret out of the
#: unit in the first place: the token has nowhere to enter, because the unit
#: file is world-readable and the environment file beside it is not.
def test_no_secret_is_written_into_the_unit() -> None:
    unit = _unit()
    assert "a-token" not in unit
    assert "EnvironmentFile=/etc/osint-console.env" in unit


def test_the_environment_file_is_one_key_per_line() -> None:
    rendered = env_file_text(ENV)
    assert "API_BIND=100.100.100.100" in rendered
    assert rendered.endswith("\n")
    assert len(rendered.strip().splitlines()) == len(ENV)


#: systemd's EnvironmentFile is not a shell. A quoted value arrives with its
#: quotes attached, and an origin list that begins with a quote character
#: matches no origin at all.
def test_the_environment_file_does_not_quote_values() -> None:
    rendered = env_file_text({"API_CORS_ORIGINS": "http://a:3000,http://b:3000"})
    assert rendered.strip() == "API_CORS_ORIGINS=http://a:3000,http://b:3000"


def test_a_value_with_a_newline_is_refused() -> None:
    #: A newline would silently truncate the value and turn the rest into a
    #: key systemd does not know.
    with pytest.raises(ValueError):
        env_file_text({"API_CORS_ORIGINS": "http://a:3000\nEVIL=1"})


def test_a_value_ending_in_a_backslash_is_refused() -> None:
    #: systemd's EnvironmentFile parser reads a trailing backslash as a line
    #: continuation and merges the next line into this value, corrupting
    #: both — the same failure the newline check exists to catch.
    with pytest.raises(ValueError):
        env_file_text({"API_CORS_ORIGINS": "http://a:3000\\"})


def test_a_value_starting_with_a_quote_is_refused() -> None:
    #: A leading quote is quote-processed by systemd, same as a trailing one
    #: — arriving already carrying one is refused rather than silently kept.
    with pytest.raises(ValueError):
        env_file_text({"API_CORS_ORIGINS": '"http://a:3000'})
