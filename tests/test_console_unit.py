"""The console's service unit, checked on what it renders.

systemd is not this project's to verify — the daemon is the operating
system's. What is this project's is the text handed to it, and every failure
worth catching here is a failure of that text: a unit that reports success
without proving its route, one that does not come back after a crash, one that
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
    "API_BIND": "127.0.0.1",
    "NEXT_PUBLIC_API_URL": "http://board.example-tailnet.ts.net:8000",
    "NEXT_PUBLIC_API_TOKEN": "a-token",
}


def _unit() -> str:
    return unit_text(
        working_dir="/srv/osint/osint-frontend",
        env_file="/etc/osint-console.env",
        bind="127.0.0.1",
        port=3000,
        commit_file="/srv/osint/osint-frontend/.next/BUILD_COMMIT",
        user="board",
        group="board",
    )


def test_the_unit_is_named_for_what_it_runs() -> None:
    assert UNIT_NAME == "osint-console.service"


#: Tailscale owns the private HTTPS edge, while the console's own loopback bind
#: remains independent of when that edge reaches the control plane.
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
    assert "-H 127.0.0.1" in unit
    assert "-p 3000" in unit


def test_it_proves_the_same_origin_api_proxy() -> None:
    unit = _unit()
    assert "ExecStartPost=" in unit
    assert "http://127.0.0.1:3000/api/health" in unit
    assert "/usr/bin/timeout 90" in unit


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
    assert "API_BIND=127.0.0.1" in rendered
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


STACK_BIND = "127.0.0.1"


def _stack() -> str:
    return stack_unit_text(
        working_dir="/srv/osint",
        bind=STACK_BIND,
    )


class TestTheContainersComeBackAfterAReboot:
    """The failure that only ever happens at boot, which is the worst kind.

    The first serve mode published the API on the board's tailnet address.
    Dockerd could restore the container before that address existed and leave
    uvicorn healthy inside a container with no network endpoint. No process
    exited, and the in-container health check still passed.

    The console recovers on its own, so what the operator sees from the phone
    is a page that loads with every panel empty.
    """

    def test_the_unit_is_named_for_what_it_starts(self) -> None:
        assert STACK_UNIT_NAME == "osint-stack.service"

    #: The local stack needs Docker, not the tailnet. Removing the dependency
    #: is what lets it become healthy while the router is still booting.
    def test_it_is_ordered_after_docker_only(self) -> None:
        unit = _stack()
        assert "After=docker.service" in unit
        assert "Wants=docker.service" in unit
        assert "tailscaled.service" not in unit
        assert "network-online.target" not in unit

    #: No address wait remains because loopback exists before either daemon.
    def test_it_has_no_tailnet_address_guard(self) -> None:
        unit = _stack()
        assert "ExecStartPre=" not in unit
        assert "ip -4 -o addr show" not in unit

    #: The container health check asks localhost inside the container. This
    #: asks through Docker's host-published port, the part that actually broke.
    def test_it_proves_the_host_published_api(self) -> None:
        unit = _stack()
        assert "ExecStartPost=" in unit
        assert "scripts/probe-api.sh" in unit
        assert "/usr/bin/timeout 90" in unit
        assert "TimeoutStartSec=" in unit
        assert "Restart=on-failure" in unit

    #: The port comes from `.env` when compose reconciles the service, then the
    #: probe asks Docker for the mapping it actually made. A port changed after
    #: installation therefore cannot be reverted by a stale unit at reboot.
    def test_it_does_not_persist_mutable_dot_env_settings(self) -> None:
        unit = _stack()
        assert "API_PORT=" not in unit
        assert "API_CORS_ORIGINS=" not in unit
        assert "http://127.0.0.1:8000/health" not in unit

    #: Reconciliation still applies source and configuration changes.
    def test_it_reconciles_the_containers_rather_than_only_ordering_them(self) -> None:
        unit = _stack()
        assert "docker compose up -d" in unit
        assert "Type=oneshot" in unit
        assert "RemainAfterExit=yes" in unit

    #: The console starts only after the stack's host-level probe passes.
    def test_the_console_is_ordered_behind_it(self) -> None:
        assert f"Before={UNIT_NAME}" in _stack()

    #: Mode, unlike configuration, is stable: the stack must always start the
    #: app profile with its API published only on loopback.
    def test_it_carries_only_the_stable_serve_mode(self) -> None:
        unit = _stack()
        assert f'Environment="API_BIND={STACK_BIND}"' in unit
        assert 'Environment="COMPOSE_PROFILES=app"' in unit

    #: Unit files are world-readable. `API_AUTH_TOKEN` reaches the containers
    #: through compose's own reading of `.env`, and so has no reason to be
    #: here — the same split the console's unit and its environment file make.
    def test_no_secret_reaches_the_unit(self) -> None:
        assert "API_AUTH_TOKEN" not in _stack()

    @pytest.mark.parametrize("value", ['127.0.0.1"', "127.0.0.1\nEVIL=1"])
    def test_a_bind_systemd_would_misread_is_refused(self, value: str) -> None:
        with pytest.raises(ValueError):
            stack_unit_text(
                working_dir="/srv/osint",
                bind=value,
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
