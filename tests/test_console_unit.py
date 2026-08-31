"""The console's service unit, checked on what it renders.

systemd is not this project's to verify — the daemon is the operating
system's. What is this project's is the text handed to it, and every failure
worth catching here is a failure of that text: a unit that starts before the
address it binds exists, one that does not come back after a crash, one that
writes a secret into a file the whole machine can read.
"""

from __future__ import annotations

import pytest

from app.devx.console_unit import (
    STACK_UNIT_NAME,
    UNIT_NAME,
    env_file_text,
    stack_unit_text,
    unit_text,
)

ENV = {
    "API_BIND": "100.100.100.100",
    "NEXT_PUBLIC_API_URL": "http://board.example-tailnet.ts.net:8000",
    "NEXT_PUBLIC_API_TOKEN": "a-token",
}


def _unit() -> str:
    return unit_text(
        working_dir="/srv/osint/osint-frontend",
        env_file="/etc/osint-console.env",
        bind="100.100.100.100",
        port=3000,
        commit_file="/srv/osint/osint-frontend/.next/BUILD_COMMIT",
        user="board",
        group="board",
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
    assert "WorkingDirectory=/srv/osint/osint-frontend" in _unit()


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


#: An invented tailnet address, inside the range Tailscale hands out, with no
#: machine behind it.
STACK_BIND = "100.100.100.100"


def _stack() -> str:
    return stack_unit_text(
        working_dir="/srv/osint",
        bind=STACK_BIND,
        environment={
            "COMPOSE_PROFILES": "app",
            "API_BIND": STACK_BIND,
            "API_CORS_ORIGINS": "http://board.example-tailnet.ts.net:3000",
        },
    )


class TestTheContainersComeBackAfterAReboot:
    """The failure that only ever happens at boot, which is the worst kind.

    Serve mode publishes the API on the board's tailnet address. Every earlier
    mode bound `127.0.0.1` or `0.0.0.0`, which exist as soon as the kernel is
    up; `100.x.y.z` exists only once tailscaled has configured an interface.
    Nothing orders `docker.service` against `tailscaled.service`, so dockerd
    can restore the `api` container first, fail the port allocation with
    `bind: cannot assign requested address`, and leave it down — a failed
    *start* is not an *exit*, so `restart: unless-stopped` never fires.

    The console recovers on its own, so what the operator sees from the phone
    is a page that loads with every panel empty.
    """

    def test_the_unit_is_named_for_what_it_starts(self) -> None:
        assert STACK_UNIT_NAME == "osint-stack.service"

    #: Necessary, and — the point of the wait below — not sufficient.
    def test_it_is_ordered_after_docker_and_the_tailnet(self) -> None:
        unit = _stack()
        assert "After=docker.service tailscaled.service network-online.target" in unit
        assert "Wants=docker.service tailscaled.service network-online.target" in unit

    #: tailscaled is `Type=notify` and reports ready when the daemon is up,
    #: which is before it has reached the control plane and put an address on
    #: an interface. Ordering narrows the race; only waiting for the address
    #: closes it. No interface is named: the address being on any of them is
    #: the entire precondition for binding it.
    def test_it_waits_for_the_address_itself_and_not_only_for_the_daemon(self) -> None:
        unit = _stack()
        assert "ExecStartPre=" in unit
        wait = next(line for line in unit.splitlines() if line.startswith("ExecStartPre="))
        assert f'" {STACK_BIND}/"' in wait
        assert "until" in wait
        assert "tailscale0" not in wait

    #: systemd expands `$word` inside an Exec line before `sh` ever sees it, so
    #: a loop counter would arrive empty and the loop would run once or not at
    #: all. The wait is written with no shell variable for that reason.
    def test_the_wait_uses_no_shell_variable(self) -> None:
        wait = next(line for line in _stack().splitlines() if line.startswith("ExecStartPre="))
        assert "$" not in wait

    #: An unbounded wait with no timeout is a boot that hangs. Five minutes and
    #: then a journal line saying so is the truth; retrying covers a tailnet
    #: that came up slowly.
    def test_the_wait_is_bounded_and_tried_again(self) -> None:
        unit = _stack()
        assert "TimeoutStartSec=" in unit
        assert "Restart=on-failure" in unit

    #: `up -d` starts a container that exists and is not running, which is
    #: precisely the state dockerd leaves the api in when it lost the race.
    #: Ordering alone could not repair that; reconciling can.
    def test_it_reconciles_the_containers_rather_than_only_ordering_them(self) -> None:
        unit = _stack()
        assert "docker compose up -d" in unit
        assert "Type=oneshot" in unit
        assert "RemainAfterExit=yes" in unit

    #: The console proxies to the API on this address. Ordered behind the
    #: stack, it starts with that upstream available instead of serving an
    #: empty page while the containers recover from the bind race.
    def test_the_console_is_ordered_behind_it(self) -> None:
        assert f"Before={UNIT_NAME}" in _stack()

    #: `API_BIND` and the derived origin list exist only in the shell that
    #: derived them — `.env` has neither — and compose substitutes from the
    #: process environment first. Without them here the boot-time start would
    #: publish on `.env`'s default and refuse the phone's preflight.
    def test_it_carries_what_compose_cannot_read_from_dot_env(self) -> None:
        unit = _stack()
        assert f'Environment="API_BIND={STACK_BIND}"' in unit
        assert 'Environment="COMPOSE_PROFILES=app"' in unit
        assert "API_CORS_ORIGINS=http://board.example-tailnet.ts.net:3000" in unit

    #: Unit files are world-readable. `API_AUTH_TOKEN` reaches the containers
    #: through compose's own reading of `.env`, and so has no reason to be
    #: here — the same split the console's unit and its environment file make.
    def test_no_secret_reaches_the_unit(self) -> None:
        assert "API_AUTH_TOKEN" not in _stack()

    #: A double quote ends the `Environment="KEY=value"` assignment early and
    #: turns the rest of the value into a second, malformed one.
    @pytest.mark.parametrize("value", ['http://a:3000"', "http://a:3000\nEVIL=1"])
    def test_a_value_systemd_would_misread_is_refused(self, value: str) -> None:
        with pytest.raises(ValueError):
            stack_unit_text(
                working_dir="/srv/osint",
                bind=STACK_BIND,
                environment={"API_CORS_ORIGINS": value},
            )

    def test_it_runs_from_the_directory_compose_is_defined_in(self) -> None:
        assert "WorkingDirectory=/srv/osint" in _stack()

    def test_it_is_enabled_at_boot(self) -> None:
        assert "WantedBy=multi-user.target" in _stack()


class TestTheConsoleDoesNotRunAsRoot:
    """The branch's safety argument is about the network. This one is not.

    Nothing in `next start` needs privilege: it reads a build and answers HTTP.
    And the cost of root arrives before any attacker does — `next start` writes
    `.next/cache` inside the checkout, so a root service turns a directory the
    operator owns into one they do not, and their next non-root
    `make serve-build` fails on `EACCES` in their own files.
    """

    def test_it_runs_as_the_account_that_installed_it(self) -> None:
        unit = _unit()
        assert "User=board" in unit
        assert "Group=board" in unit

    #: Each of these holds for a process that reads a build and answers HTTP.
    @pytest.mark.parametrize(
        "directive",
        [
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "ProtectKernelTunables=yes",
            "ProtectControlGroups=yes",
            "RestrictSUIDSGID=yes",
        ],
    )
    def test_it_gives_up_what_it_does_not_need(self, directive: str) -> None:
        assert directive in _unit()

    #: `strict` makes the working directory read-only as well, and `next start`
    #: writes .next/cache there — hardening that stops the service starting is
    #: not hardening, it is an outage with a good reason.
    def test_the_filesystem_is_protected_only_as_far_as_the_build_allows(self) -> None:
        unit = _unit()
        assert "ProtectSystem=full" in unit
        assert "ProtectSystem=strict" not in unit

    #: The checkout is under the operator's home. Protecting home puts the
    #: build the service exists to serve out of its reach.
    def test_home_is_not_protected_because_the_build_lives_there(self) -> None:
        #: Directive lines only — the comment above it names the setting in
        #: order to explain why it is absent, and that explanation is the
        #: reason the line must stay absent.
        directives = [line for line in _unit().splitlines() if not line.startswith("#")]
        assert not any(line.startswith("ProtectHome=") for line in directives)
