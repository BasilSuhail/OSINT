"""The stack is loopback-only until sharing is asked for (#928).

#824 moved the stores to `127.0.0.1` and added the optional shared secret, but
left the two ports a browser uses published on every interface. A laptop that
runs the stack on an untrusted network was serving the console and
`POST /brain/ask` to it.

Three settings have to agree before another device can load the dashboard, and
disagreeing silently is what makes this worth testing rather than documenting:

- the API's published bind address, or the guest cannot reach the API at all;
- `API_CORS_ORIGINS`, or the guest's browser makes the request and then throws
  the answer away at the preflight;
- `NEXT_PUBLIC_API_URL`, which is compiled into the bundle the guest downloads
  and must therefore name an address resolvable from the *guest*. The default
  `http://localhost:8000` resolves, on a guest device, to the guest.

The shared secret is deliberately not part of share mode: the guest loads the
frontend, so `NEXT_PUBLIC_API_TOKEN` is in the bundle they download.

Addresses here come from the documentation range (RFC 5737) rather than a real
private one: a repository is a poor place to record the shape of anybody's home
network, and nothing under test cares which range the address is from.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.devx.lan_share import (
    ALL_INTERFACES,
    LOOPBACK,
    ShareAddressError,
    locked_env,
    render_exports,
    share_env,
)

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
DEV_UP = ROOT / "scripts" / "dev-up.sh"
MAKEFILE = ROOT / "Makefile"


def test_locked_is_the_default_shape() -> None:
    env = locked_env()
    assert env["API_BIND"] == LOOPBACK
    assert env["FRONTEND_BIND"] == LOOPBACK


def test_locked_does_not_touch_the_browser_facing_settings() -> None:
    """Locked mode leaves `.env` to speak for itself.

    Emitting an origin list or an API URL here would override whatever the
    operator configured, for no gain: loopback defaults already work.
    """
    env = locked_env()
    assert "NEXT_PUBLIC_API_URL" not in env
    assert "API_CORS_ORIGINS" not in env


def test_share_publishes_on_every_interface() -> None:
    env = share_env("203.0.113.42")
    assert env["API_BIND"] == ALL_INTERFACES
    assert env["FRONTEND_BIND"] == ALL_INTERFACES


def test_share_points_the_bundle_at_an_address_a_guest_can_resolve() -> None:
    env = share_env("203.0.113.42")
    assert env["NEXT_PUBLIC_API_URL"] == "http://203.0.113.42:8000"
    assert "localhost" not in env["NEXT_PUBLIC_API_URL"]


def test_share_adds_the_guest_origin_without_dropping_the_configured_ones() -> None:
    env = share_env("203.0.113.42", cors_origins="http://localhost:3000,http://localhost:3001")
    origins = env["API_CORS_ORIGINS"].split(",")
    assert origins == [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://203.0.113.42:3000",
    ]


def test_share_does_not_repeat_an_origin_already_configured() -> None:
    env = share_env("203.0.113.42", cors_origins="http://203.0.113.42:3000,http://localhost:3000")
    assert env["API_CORS_ORIGINS"].count("http://203.0.113.42:3000") == 1


def test_share_falls_back_to_the_localhost_origins_when_none_configured() -> None:
    env = share_env("203.0.113.42", cors_origins="")
    origins = env["API_CORS_ORIGINS"].split(",")
    assert "http://localhost:3000" in origins
    assert "http://203.0.113.42:3000" in origins


def test_share_honours_non_default_ports() -> None:
    env = share_env("203.0.113.42", api_port=9000, frontend_port=3001, cors_origins="")
    assert env["NEXT_PUBLIC_API_URL"] == "http://203.0.113.42:9000"
    assert "http://203.0.113.42:3001" in env["API_CORS_ORIGINS"].split(",")


def test_share_names_the_host_the_dev_server_must_allow() -> None:
    """The fourth setting that has to agree (#930).

    `next dev` refuses `/_next/*` dev resources for any host that is not
    localhost, so the dashboard reached the guest as a shell with a dead
    websocket. The host goes to `allowedDevOrigins`, bare: no scheme, no port.
    """
    env = share_env("203.0.113.42")
    assert env["LAN_SHARE_HOST"] == "203.0.113.42"


def test_locked_allows_no_extra_dev_origin() -> None:
    assert "LAN_SHARE_HOST" not in locked_env()


def test_share_reports_the_url_to_hand_over() -> None:
    env = share_env("203.0.113.42", frontend_port=3000)
    assert env["LAN_SHARE_URL"] == "http://203.0.113.42:3000"


@pytest.mark.parametrize(
    "address",
    [
        "",
        "   ",
        # Every label numeric means somebody meant an address and mistyped it.
        # No hostname looks like this, so reading it as one would turn a typo
        # into a name that never resolves.
        "999.1.1.1",
        # Colons: IPv6, or a port appended by hand. The bundle URL and the
        # compose mapping would both need bracket syntax for the first, and the
        # port is already supplied separately.
        "::1",
        "example.invalid:3000",
        # A scheme or a path makes it a URL. This wants a bare host.
        "http://example.invalid",
        "example.invalid/console",
        "two words",
        "-leading.dash",
    ],
)
def test_share_refuses_an_address_a_guest_could_not_use(address: str) -> None:
    """A wrong address fails now, with a name, rather than as an empty console."""
    with pytest.raises(ShareAddressError):
        share_env(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "localhost", "LocalHost"])
def test_share_refuses_an_address_that_means_this_machine(address: str) -> None:
    """On a guest device every one of these names the guest, not the host."""
    with pytest.raises(ShareAddressError):
        share_env(address)


class TestPinnedHost:
    """A pinned host, for reaching the console from off the local network (#974).

    The detected address is private. It is not only the link — it is compiled
    into the bundle the guest downloads, so a guest arriving by any other route
    loads a console whose every API call goes somewhere they cannot reach.
    """

    def test_a_name_is_accepted_where_only_an_address_was(self) -> None:
        env = share_env("console.invalid", frontend_port=3000, api_port=8000)
        assert env["NEXT_PUBLIC_API_URL"] == "http://console.invalid:8000"
        assert env["LAN_SHARE_URL"] == "http://console.invalid:3000"
        assert env["LAN_SHARE_HOST"] == "console.invalid"

    def test_the_bind_is_unchanged_by_pinning(self) -> None:
        env = share_env("console.invalid")
        assert env["API_BIND"] == ALL_INTERFACES
        assert env["FRONTEND_BIND"] == ALL_INTERFACES

    #: Pinning must not take away the network that already worked.
    #:
    #: Stated as the whole list rather than as memberships: the order and the
    #: absence of a repeat are both part of what this promises, and a
    #: membership check states neither.
    def test_the_detected_address_stays_in_the_origin_list(self) -> None:
        env = share_env("console.invalid", also_reachable_at=("203.0.113.42",), frontend_port=3000)
        assert env["API_CORS_ORIGINS"].split(",") == [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://console.invalid:3000",
            "http://203.0.113.42:3000",
        ]

    def test_an_origin_is_never_listed_twice(self) -> None:
        env = share_env("203.0.113.42", also_reachable_at=("203.0.113.42",), frontend_port=3000)
        origins = env["API_CORS_ORIGINS"].split(",")
        assert origins.count("http://203.0.113.42:3000") == 1

    #: The pinned host is what the guest typed, so it is the one `next dev` has
    #: to allow — not the address this machine happens to have (#930).
    def test_the_dev_server_is_told_to_allow_the_pinned_host(self) -> None:
        env = share_env("console.invalid", also_reachable_at=("203.0.113.42",))
        assert env["LAN_SHARE_HOST"] == "console.invalid"

    def test_an_unusable_extra_address_is_dropped_rather_than_fatal(self) -> None:
        """Detection failing must not stop a pin that was given explicitly."""
        env = share_env("console.invalid", also_reachable_at=("", "127.0.0.1"), frontend_port=3000)
        assert env["API_CORS_ORIGINS"].split(",") == [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://console.invalid:3000",
        ]


def test_exports_are_quoted_for_eval() -> None:
    rendered = render_exports({"A": "one two", "B": "x'y"})
    assert rendered.splitlines()[0].startswith("export A=")
    # The shell must see one argument, whatever the value contains.
    assert "one two" in rendered
    assert rendered.count("\n") == 2


def test_compose_publishes_the_api_on_loopback_by_default() -> None:
    """The default has to be the safe one.

    An operator who never reads this file, and never runs `make share`, is
    closed. That is the property #928 is about, and it lives in one string.
    """
    compose = yaml.safe_load(COMPOSE.read_text())
    ports = compose["services"]["api"]["ports"]
    assert ports == ["${API_BIND:-127.0.0.1}:${API_PORT:-8000}:8000"]


def test_no_service_publishes_on_every_interface_by_default() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    for name, service in compose["services"].items():
        for mapping in service.get("ports", []):
            assert "127.0.0.1" in str(mapping), f"{name} publishes {mapping} beyond loopback"


def test_dev_up_binds_the_frontend_explicitly() -> None:
    """`next dev` defaults to every interface, so the bind must be passed.

    Left implicit, locked mode would close the API and leave the console open,
    which is the half-fix that reads as a whole one.
    """
    script = DEV_UP.read_text()
    assert "pnpm dev -H '$FRONTEND_BIND'" in script
    assert "export API_BIND=127.0.0.1 FRONTEND_BIND=127.0.0.1" in script


def test_dev_up_reuses_the_dashboard_only_when_the_whole_mode_matches() -> None:
    """Bind address alone is not the identity of a running dashboard.

    Two shares on two networks have the same bind and different addresses in
    the bundle. Comparing only the bind would reuse a dashboard pointing at an
    address that no longer resolves, which shows up as an empty console rather
    than as an error.

    Every value the bundle is built from belongs here, for the same reason.
    `NEXT_PUBLIC_ASK_ENABLED` decides whether the console draws the ask control
    at all, so leaving it out means an operator who edits `.env` to turn
    questions back on is told the frontend is already running and keeps being
    served the build without the box — following the documented instruction and
    watching it do nothing.
    """
    script = DEV_UP.read_text()
    assert (
        'printf \'%s %s %s\' "$FRONTEND_BIND" "${NEXT_PUBLIC_API_URL:-}"'
        ' "${NEXT_PUBLIC_ASK_ENABLED:-}"' in script
    )
    # The signature must be taken after the .env values are loaded, or the
    # comparison and the recorded value disagree and every run restarts.
    body = script.split("spawn_frontend() {", 1)[1]
    assert body.index("load_frontend_public_env") < body.index("frontend_mode_signature")


def test_next_config_reads_the_shared_host() -> None:
    """The derived value has to reach the setting it exists for (#930).

    The parsing is tested next to the frontend code; what this pins is the
    wiring, which is the half that was missing rather than wrong.
    """
    config = (ROOT / "osint-frontend" / "next.config.mjs").read_text()
    assert "allowedDevOrigins" in config
    assert "process.env.LAN_SHARE_HOST" in config


def test_make_share_exists_and_does_not_persist_the_choice() -> None:
    """Share is a run-time flag, never a file edit.

    A stack shared at home and restarted elsewhere must come back closed, so
    nothing may write the flag into `.env`.
    """
    makefile = MAKEFILE.read_text()
    assert "\nshare:" in makefile
    assert "LAN_SHARE=1" in makefile
    assert "LAN_SHARE" not in (ROOT / "env.example").read_text()


class TestTheDashboardReceivesItsSettings:
    """`.env` is at the repository root; the dashboard runs a directory down.

    Next never reads that file, so `load_frontend_public_env` is the only route
    anything in it takes to the browser bundle. A key that does not pass
    through here is a key the console does not have (#976).
    """

    #: The failure this replaces: every request 401, drawn on screen as "no
    #: events" rather than as a fault, because the one key the requests depend
    #: on was missing from a hand-kept list.
    def test_every_public_key_is_passed_through_rather_than_a_chosen_few(self) -> None:
        script = DEV_UP.read_text()
        assert "NEXT_PUBLIC_*)" in script

    def test_no_hand_kept_list_of_public_keys_remains(self) -> None:
        """A list here is a copy of env.example, and copies fall behind."""
        script = DEV_UP.read_text()
        assert "NEXT_PUBLIC_API_URL|NEXT_PUBLIC_" not in script

    def test_the_token_the_console_authenticates_with_is_documented(self) -> None:
        assert "NEXT_PUBLIC_API_TOKEN=" in (ROOT / "env.example").read_text()


class TestTheDataDirectoryBelongsToTheOperator:
    """A bind mount whose source is missing is created by the daemon, as root.

    The containers run as the operator (`DOCKER_UID`), so on a fresh clone
    `data/` arrived root-owned and beat crash-looped on
    `Permission denied: '/data/celerybeat-schedule'`. The story export failed the
    same way on `/data/exports`. Setting the uid was half the fix; the directory
    having the right owner in the first place is the other half.
    """

    def test_the_script_creates_it_before_compose_can(self) -> None:
        script = DEV_UP.read_text()
        assert "ensure_data_dir" in script

    #: After the settings, because the location is one of them — reading .env
    #: before `env_setup.py` has written it would default every time.
    def test_it_runs_after_the_settings_are_written(self) -> None:
        body = DEV_UP.read_text()
        assert body.index("env_setup.py sync") < body.index("ensure_data_dir()")

    #: Before anything that mounts it, or the daemon gets there first.
    def test_it_runs_before_the_stores_come_up(self) -> None:
        body = DEV_UP.read_text()
        assert body.index("ensure_data_dir\n") < body.index("compose_up")

    #: `data/postgres` belongs to the database image's own user. Recursively
    #: chowning the tree is how you stop Postgres starting, so nothing here does.
    def test_it_never_chowns_what_is_already_there(self) -> None:
        script = DEV_UP.read_text()
        assert "chown -R" not in script


class TestEveryCommandWorksOnAFreshClone:
    """The analysis targets called `.venv/bin/python` outright.

    Nothing creates a host virtualenv — the backend runs in a container — so on a
    machine that had only ever followed the README, all twenty-nine of them
    failed. `make stories` is documented as the way to build the story clusters
    and could not run. The workaround was `docker compose exec` typed by hand.
    """

    def test_no_target_hard_codes_the_host_virtualenv(self) -> None:
        recipes = [
            line
            for line in MAKEFILE.read_text().splitlines()
            if line.startswith("\t") and ".venv/bin/python" in line
        ]
        assert recipes == []

    def test_the_runner_prefers_a_virtualenv_and_falls_back_to_the_container(self) -> None:
        assert "RUN_PY ?=" in MAKEFILE.read_text()
        body = MAKEFILE.read_text()
        runner = body[body.index("RUN_PY ?=") :][:400]
        assert ".venv/bin/python" in runner
        assert "docker compose exec -T worker python" in runner

    #: `scripts/` is not copied into the image — deliberately, it is host-side
    #: tooling — so a target that runs a script from there cannot use the
    #: container path. This one moved into `app/` for that reason.
    def test_prune_runs_a_module_the_image_contains(self) -> None:
        assert "$(RUN_PY) -m app.prune_now" in MAKEFILE.read_text()
        assert not (ROOT / "scripts" / "prune_now.py").exists()
        assert (ROOT / "app" / "prune_now.py").exists()


class TestDataSizeDoesNotContradictItself:
    """`du` exits non-zero when it cannot descend into a directory.

    It cannot descend into `data/postgres` — that belongs to the database image's
    own user — so `|| echo "no data yet"` fired on a populated directory and
    printed the denial as an absence, directly under the sizes it had just listed.
    """

    def test_emptiness_is_decided_by_looking_not_by_an_exit_code(self) -> None:
        recipe = MAKEFILE.read_text()
        recipe = recipe[recipe.index("data-size:") :][:700]
        assert "ls -A" in recipe
        #: The bug was the fallback hanging off du's status.
        assert 'du -sh "$(OSINT_DATA_DIR)"/* 2>/dev/null || echo' not in recipe

    #: An unprivileged `du` reports the directory entry for Postgres, not the
    #: database, so the largest number on screen is the one it cannot see.
    def test_it_says_the_postgres_number_needs_sudo(self) -> None:
        recipe = MAKEFILE.read_text()
        assert "sudo for the true Postgres size" in recipe
