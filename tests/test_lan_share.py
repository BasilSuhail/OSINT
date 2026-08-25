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

import subprocess
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from app.devx import lan_share
from app.devx.lan_share import (
    ALL_INTERFACES,
    LOOPBACK,
    ServeRefused,
    ShareAddressError,
    locked_env,
    render_exports,
    serve_env,
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


#: Tailscale hands out addresses from the carrier-grade NAT range and names
#: hosts under a tailnet's own domain. Both here are invented: an address
#: inside the range with no machine behind it, and a domain that cannot exist.
SERVE_HOST = "board.example-tailnet.ts.net"
SERVE_ADDRESS = "100.100.100.100"


class TestServeMode:
    #: The whole point of the mode. Not 0.0.0.0: that also publishes on the
    #: home wifi, which is share mode's exposure arriving through a mode that
    #: never said it would.
    def test_it_binds_the_tailnet_address_and_not_every_interface(self) -> None:
        env = serve_env(SERVE_HOST, SERVE_ADDRESS, api_token="a-token")
        assert env["API_BIND"] == SERVE_ADDRESS
        assert env["FRONTEND_BIND"] == SERVE_ADDRESS
        assert ALL_INTERFACES not in env.values()

    #: Compiled into the bundle the phone downloads, so it must name what the
    #: phone can resolve — the tailnet name, never the address the board calls
    #: itself.
    def test_the_bundle_points_at_the_tailnet_name(self) -> None:
        env = serve_env(SERVE_HOST, SERVE_ADDRESS, api_token="a-token")
        assert env["NEXT_PUBLIC_API_URL"] == f"http://{SERVE_HOST}:8000"

    def test_it_adds_the_tailnet_origin_without_dropping_configured_ones(self) -> None:
        env = serve_env(
            SERVE_HOST,
            SERVE_ADDRESS,
            cors_origins="http://localhost:3000",
            api_token="a-token",
        )
        origins = env["API_CORS_ORIGINS"].split(",")
        assert "http://localhost:3000" in origins
        assert f"http://{SERVE_HOST}:3000" in origins

    def test_it_honours_non_default_ports(self) -> None:
        env = serve_env(
            SERVE_HOST, SERVE_ADDRESS, api_port=9000, frontend_port=4000, api_token="a-token"
        )
        assert env["NEXT_PUBLIC_API_URL"] == f"http://{SERVE_HOST}:9000"
        assert f"http://{SERVE_HOST}:4000" in env["API_CORS_ORIGINS"]

    def test_it_reports_the_url_to_open(self) -> None:
        env = serve_env(SERVE_HOST, SERVE_ADDRESS, api_token="a-token")
        assert env["OSINT_SERVE_URL"] == f"http://{SERVE_HOST}:3000"
        assert env["OSINT_SERVE_HOST"] == SERVE_HOST

    #: `next start` has no equivalent of the dev server's host allow-list, so
    #: emitting the setting share mode needs would be a setting that does
    #: nothing.
    def test_it_emits_no_dev_server_host(self) -> None:
        assert "LAN_SHARE_HOST" not in serve_env(SERVE_HOST, SERVE_ADDRESS, api_token="a-token")

    #: An address outside the tailnet range is the home wifi, or a mistake.
    #: Either way it is not the interface this mode means.
    @pytest.mark.parametrize("address", ["192.0.2.10", "0.0.0.0", "127.0.0.1"])
    def test_it_refuses_an_address_that_is_not_on_the_tailnet(self, address: str) -> None:
        with pytest.raises(ServeRefused):
            serve_env(SERVE_HOST, address, api_token="a-token")

    #: On a laptop an empty token is a convenience. On a board that is up all
    #: the time and reachable from a phone, it is the only thing between a
    #: tailnet device and an endpoint that spends model inference per call.
    @pytest.mark.parametrize("token", ["", "   "])
    def test_it_refuses_to_serve_without_a_token(self, token: str) -> None:
        with pytest.raises(ServeRefused) as raised:
            serve_env(SERVE_HOST, SERVE_ADDRESS, api_token=token)
        assert "API_AUTH_TOKEN" in str(raised.value)

    def test_it_refuses_a_host_a_phone_could_not_resolve(self) -> None:
        with pytest.raises(ShareAddressError):
            serve_env("localhost", SERVE_ADDRESS, api_token="a-token")


class TestReadingTheTailnet:
    #: The shape `tailscale status --json` returns. Trimmed to the two fields
    #: this reads; the real payload carries the whole tailnet, which is
    #: exactly why none of it is pasted here.
    STATUS: ClassVar[dict] = {
        "Self": {
            "DNSName": "board.example-tailnet.ts.net.",
            "TailscaleIPs": ["100.100.100.100", "fd7a:1::1"],
        },
        "CurrentTailnet": {
            "MagicDNSEnabled": True,
            "MagicDNSSuffix": "example-tailnet.ts.net",
        },
    }

    def test_it_reads_the_name_and_the_address(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: self.STATUS)
        assert lan_share.tailnet_identity() == (SERVE_HOST, SERVE_ADDRESS)

    #: The name comes back fully qualified, with the root dot. A URL built
    #: from it unstripped is a URL that does not work.
    def test_it_drops_the_trailing_dot(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: self.STATUS)
        host, _ = lan_share.tailnet_identity()
        assert not host.endswith(".")

    #: The v4 address, not whichever came first. A bind address in brackets is
    #: a shape neither compose nor the unit has been tried with.
    def test_it_takes_the_v4_address(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: self.STATUS)
        _, address = lan_share.tailnet_identity()
        assert ":" not in address

    @pytest.mark.parametrize("status", [{}, {"Self": {}}, {"Self": {"TailscaleIPs": []}}])
    def test_it_refuses_when_the_tailnet_says_nothing_usable(self, monkeypatch, status) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: status)
        with pytest.raises(ServeRefused):
            lan_share.tailnet_identity()

    def test_it_refuses_when_tailscale_is_not_there(self, monkeypatch) -> None:
        def absent() -> dict:
            raise ServeRefused("tailscale is not installed or not running")

        monkeypatch.setattr(lan_share, "_tailscale_status", absent)
        with pytest.raises(ServeRefused):
            lan_share.tailnet_identity()


class TestMagicDNSIsAPrecondition:
    """The name in the bundle has to be one the phone can actually resolve.

    `Self.DNSName` is populated whether or not MagicDNS is on — it is the name
    the node *would* answer to. With it off, every step of serve mode succeeds
    and the phone gets NXDOMAIN after the reboot. And because the name is
    compiled into the bundle, the fix is another build, not a restart: the one
    precondition here whose cost is minutes rather than seconds, and the only
    one that was not checked.
    """

    OFF: ClassVar[dict] = {
        "Self": {
            "DNSName": "board.example-tailnet.ts.net.",
            "TailscaleIPs": ["100.100.100.100"],
        },
        "CurrentTailnet": {"MagicDNSEnabled": False, "MagicDNSSuffix": ""},
    }

    #: The passing case. Everything else in `TestReadingTheTailnet` rests on
    #: this too, since its fixture carries the field — stated once here so the
    #: check has a test that fails if it starts refusing a healthy tailnet.
    def test_a_tailnet_with_magic_dns_on_is_read_normally(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: TestReadingTheTailnet.STATUS)
        assert lan_share.tailnet_identity() == (SERVE_HOST, SERVE_ADDRESS)

    def test_it_refuses_when_magic_dns_is_off(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: self.OFF)
        with pytest.raises(ServeRefused) as raised:
            lan_share.tailnet_identity()
        assert "MagicDNS" in str(raised.value)

    #: A refusal that does not name the fix is a refusal the operator has to
    #: go and research. This one costs a rebuild, so it says so.
    def test_the_refusal_names_the_rebuild_and_not_a_restart(self, monkeypatch) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: self.OFF)
        with pytest.raises(ServeRefused) as raised:
            lan_share.tailnet_identity()
        message = str(raised.value)
        assert "make serve-build" in message
        assert "admin console" in message

    #: Not assumed good. A tailnet that says nothing about MagicDNS costs one
    #: look at the admin console to clear; assuming it costs a build, a reboot
    #: and a console that loads nothing.
    @pytest.mark.parametrize(
        "status",
        [
            {
                "Self": {
                    "DNSName": "board.example-tailnet.ts.net.",
                    "TailscaleIPs": ["100.100.100.100"],
                }
            },
            {
                "Self": {
                    "DNSName": "board.example-tailnet.ts.net.",
                    "TailscaleIPs": ["100.100.100.100"],
                },
                "CurrentTailnet": {},
            },
        ],
    )
    def test_it_refuses_when_the_tailnet_says_nothing_about_magic_dns(
        self, monkeypatch, status
    ) -> None:
        monkeypatch.setattr(lan_share, "_tailscale_status", lambda: status)
        with pytest.raises(ServeRefused):
            lan_share.tailnet_identity()


class TestOneRoundTripPerAttempt:
    """Both preconditions a board can fail at once are asked in cost order.

    Tailscale down *and* no token is the state a board is genuinely in the
    first time serve mode is run on it. Asking the tailnet first told the
    operator about Tailscale alone; the token refusal waited for the next
    attempt. The token is an environment variable and needs no subprocess, so
    it goes first and the cheap answer is never the second one.
    """

    def test_the_token_is_refused_before_tailscale_is_asked(self, monkeypatch, capsys) -> None:
        def unreachable() -> dict:
            raise AssertionError("the tailnet was asked before the token was checked")

        #: Serve mode is the board's, and the board is Linux — say so, or this
        #: reads the platform refusal that now comes before either of these.
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr(lan_share, "tailnet_identity", unreachable)
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        assert lan_share.main(["serve"]) == 1
        assert "API_AUTH_TOKEN" in capsys.readouterr().err

    #: A refusal prints no exports: the caller evals this output.
    def test_the_refusal_emits_nothing_to_eval(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr(lan_share, "tailnet_identity", lambda: (SERVE_HOST, SERVE_ADDRESS))
        monkeypatch.setenv("API_AUTH_TOKEN", "")
        assert lan_share.main(["serve"]) == 1
        assert capsys.readouterr().out == ""


class TestServeModeRefusesOffTheBoard:
    """Serve mode is for a machine with systemd, and asks nothing anywhere else.

    The mode derives a bind for a tailnet interface and renders systemd units,
    and `make serve-install` has always refused where there is no systemd. The
    module did not, so `python -m app.devx.lan_share serve` on a laptop still
    reached `tailscale status` — a subprocess whose result that machine had no
    use for.

    That probe outlived its parent. The parent was killed rather than exiting,
    so no `finally` and no `atexit` ran; the child was reparented and, on a
    host whose Tailscale had no running daemon to answer it, retried instead of
    failing. It was still there days later, holding tens of gigabytes.

    No cleanup handler inside Python closes that — none of them run when the
    parent is killed. What closes it is not spawning on a platform that cannot
    use the answer, which is what these pin: the refusal comes first, and the
    probe is never reached.
    """

    @staticmethod
    def _never_probed() -> dict:
        raise AssertionError("tailscale was asked on a platform that cannot use the answer")

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_it_refuses_without_spawning_anything(self, monkeypatch, capsys, platform) -> None:
        monkeypatch.setattr("sys.platform", platform)
        monkeypatch.setattr(lan_share, "_tailscale_status", self._never_probed)
        monkeypatch.setenv("API_AUTH_TOKEN", "a-token")
        assert lan_share.main(["serve"]) == 1
        assert "cannot serve" in capsys.readouterr().err

    #: An operator on a laptop sent to `tailscale up` fixes a tailnet that was
    #: never broken and arrives back here. The refusal has to name the platform.
    def test_the_refusal_names_the_platform_not_a_missing_tailnet(
        self, monkeypatch, capsys
    ) -> None:
        monkeypatch.setattr("sys.platform", "darwin")
        monkeypatch.setattr(lan_share, "_tailscale_status", self._never_probed)
        monkeypatch.setenv("API_AUTH_TOKEN", "a-token")
        lan_share.main(["serve"])
        message = capsys.readouterr().err
        assert "tailscale up" not in message
        assert "systemd" in message
        assert "darwin" in message
        assert "board" in message

    #: Ahead of the token check too. Nothing should be read, and nothing
    #: spawned, on a platform whose answer is refusal either way.
    def test_the_platform_is_refused_before_the_token(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.platform", "darwin")
        monkeypatch.setattr(lan_share, "_tailscale_status", self._never_probed)
        monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
        assert lan_share.main(["serve"]) == 1
        assert "API_AUTH_TOKEN" not in capsys.readouterr().err

    #: The caller evals this output, so a refusal prints no exports.
    def test_the_refusal_emits_nothing_to_eval(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.platform", "darwin")
        monkeypatch.setattr(lan_share, "_tailscale_status", self._never_probed)
        monkeypatch.setenv("API_AUTH_TOKEN", "a-token")
        lan_share.main(["serve"])
        assert capsys.readouterr().out == ""

    #: The passing case, so the guard has a test that fails if it starts
    #: refusing the machine the mode exists for.
    def test_serve_still_works_on_the_board(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr(lan_share, "tailnet_identity", lambda: (SERVE_HOST, SERVE_ADDRESS))
        monkeypatch.setenv("API_AUTH_TOKEN", "a-token")
        monkeypatch.delenv("OSINT_PUBLIC_HOST", raising=False)
        assert lan_share.main(["serve"]) == 0
        exported = capsys.readouterr().out
        assert f"export API_BIND={SERVE_ADDRESS}" in exported
        assert SERVE_HOST in exported

    #: Every platform keeps the laptop's two modes. `scripts/dev-up.sh` runs
    #: locked on every `make up`, so a guard that reached them would stop the
    #: stack starting on the machine it is developed on.
    @pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
    def test_locked_is_unaffected_everywhere(self, monkeypatch, capsys, platform) -> None:
        monkeypatch.setattr("sys.platform", platform)
        assert lan_share.main(["locked"]) == 0
        assert f"export API_BIND={LOOPBACK}" in capsys.readouterr().out

    @pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
    def test_share_is_unaffected_everywhere(self, monkeypatch, capsys, platform) -> None:
        monkeypatch.setattr("sys.platform", platform)
        monkeypatch.setattr(lan_share, "detect_lan_ip", lambda: "203.0.113.42")
        monkeypatch.delenv("OSINT_PUBLIC_HOST", raising=False)
        assert lan_share.main(["share"]) == 0
        assert f"export API_BIND={ALL_INTERFACES}" in capsys.readouterr().out


class TestTheTailnetProbeWaitsBriefly:
    """Ten seconds of patience bought nothing and cost a stranded child.

    A tailnet that is up answers `tailscale status --json` in milliseconds. The
    failure the timeout guards is not a slow tailnet, it is a CLI with no
    daemon to talk to — and every second of it is a second in which an aborted
    parent can leave the probe behind.
    """

    def test_the_wait_is_short(self) -> None:
        assert lan_share.TAILSCALE_STATUS_TIMEOUT == 5

    def test_the_probe_actually_passes_it(self, monkeypatch) -> None:
        seen: dict = {}

        def record(command, **kwargs):
            seen.update(kwargs)
            seen["command"] = command
            return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

        monkeypatch.setattr(lan_share.subprocess, "run", record)
        assert lan_share._tailscale_status() == {}
        assert seen["timeout"] == lan_share.TAILSCALE_STATUS_TIMEOUT
        assert seen["command"][0] == "tailscale"


def _serve_script() -> str:
    return (Path(__file__).resolve().parents[1] / "scripts/serve-up.sh").read_text()


def test_the_serve_targets_exist() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    for target in ("serve-build:", "serve-install:", "serve:"):
        assert target in makefile


#: systemd is Linux's. On anything else the install would write a file nothing
#: reads and report success, which is worse than refusing. Presence alone
#: would pass even if the check ran after the destructive work, so this pins
#: the refusal ahead of the first `systemctl` call it guards.
def test_installing_the_unit_refuses_where_there_is_no_systemd() -> None:
    script = _serve_script()
    assert "uname" in script
    assert "systemctl" in script
    install_body = script.split("cmd_install() {", 1)[1]
    assert install_body.index("require_a_board") < install_body.index("systemctl")


#: The build and the start refuse there too, which they did not.
#:
#: Both call `apply_serve_mode`, which runs `lan_share serve`, which asks
#: Tailscale for an identity a machine without systemd cannot use. The install
#: was guarded and these two were not, so the probe stayed reachable from a
#: laptop — and one such probe outlived the process that started it. The
#: refusal goes ahead of the interpreter, so nothing is spawned at all.
def test_deriving_serve_mode_refuses_before_it_spawns_anything() -> None:
    script = _serve_script()
    body = script.split("apply_serve_mode() {", 1)[1].split("\n}", 1)[0]
    assert body.index("require_a_board") < body.index("serve_python")
    assert body.index("require_a_board") < body.index("lan_share serve")


#: Both reach the guard through `apply_serve_mode`, and both must reach it
#: before the work they do — a build that refuses after `pnpm install` has
#: already spent the minutes it was refusing to be worth.
@pytest.mark.parametrize(
    ("command", "work"),
    [("cmd_build() {", "pnpm"), ("cmd_start() {", "docker compose")],
)
def test_the_board_check_comes_before_the_work(command: str, work: str) -> None:
    body = _serve_script().split(command, 1)[1].split("\n}", 1)[0]
    assert body.index("apply_serve_mode") < body.index(work)


#: The build bakes NEXT_PUBLIC_* into the bundle, so it must run with serve
#: mode's environment in place, not the shell's defaults.
def test_the_build_runs_under_serve_mode() -> None:
    script = _serve_script()
    assert "lan_share serve" in script
    assert "pnpm build" in script


#: A build whose commit is not recorded is a build whose staleness cannot be
#: seen from the journal.
def test_the_build_records_the_commit_it_built() -> None:
    assert "BUILD_COMMIT" in _serve_script()


#: The install prints the unit before writing it. A file installed into
#: /etc without being shown is a file nobody reviewed. Presence alone would
#: pass even if the reveal came after the write, so this pins `cat` (or
#: `printf`) ahead of the first command that actually writes something —
#: `sudo install`, named exactly, because the word `sudo` also appears in
#: prose the install prints.
def test_the_install_shows_the_unit_before_writing_it() -> None:
    script = _serve_script()
    assert "sudo install" in script
    assert "cat" in script or "printf" in script
    install_body = script.split("cmd_install() {", 1)[1]
    reveal = "cat" if "cat" in install_body else "printf"
    assert install_body.index(reveal) < install_body.index("sudo install")


#: `pnpm build` compiles NEXT_PUBLIC_* into the bundle from this shell's
#: environment, and NEXT_PUBLIC_API_TOKEN — how the built console
#: authenticates every request — is not among what serve mode derives; it
#: lives only in `.env`. A build that starts before `.env` is read ships a
#: console that can never authenticate.
def test_the_build_loads_dot_env_before_building() -> None:
    script = _serve_script()
    assert "load_frontend_public_env" in script
    build_body = script.split("cmd_build() {", 1)[1]
    assert build_body.index("load_frontend_public_env") < build_body.index("pnpm build")


class TestTheLaptopCommandIsNotRunAccidentallyOnTheBoard:
    """`make up` is destructive on a serving board, and silently so.

    `dev-up.sh` exports `API_BIND=127.0.0.1`. With the console's service
    installed, that recreates the api container on loopback while the service
    carries on serving the tailnet address — no port clash, so nothing
    complains, and every request from the phone is refused. `make down`
    compounds it: the containers stop, the service stays up, and the phone
    still gets a page.

    Asked rather than refused. A hard refusal in the laptop's own start script
    is a cost paid by every machine to protect one, and a loopback stack on a
    board is a thing an operator can legitimately want. Printed and confirmed,
    rather than printed alone, because a warning inside a wall of start-up
    output is a warning nobody reads.
    """

    def test_the_start_script_notices_an_enabled_console_service(self) -> None:
        script = DEV_UP.read_text()
        assert "osint-console.service" in script
        assert "systemctl is-enabled" in script

    #: Before anything is exported or started, or the warning describes a thing
    #: that has already happened.
    def test_it_asks_before_the_bind_is_chosen(self) -> None:
        script = DEV_UP.read_text()
        assert script.index("\nrefuse_if_serving\n") < script.index("\napply_network_mode\n")

    #: A warning that does not name the right command leaves the operator to
    #: guess at one.
    def test_it_names_the_command_for_this_machine(self) -> None:
        script = DEV_UP.read_text()
        body = script.split("refuse_if_serving() {", 1)[1]
        assert "make serve" in body
        assert "read -r -p" in body

    #: With nothing reading the question, the destructive answer must not be
    #: the default. The override is named in the refusal.
    def test_it_refuses_rather_than_assumes_when_nothing_can_answer(self) -> None:
        body = DEV_UP.read_text().split("refuse_if_serving() {", 1)[1]
        assert "-t 0" in body
        assert "OSINT_IGNORE_SERVING" in body

    #: Stopping a system service is not what a developer's stop command was
    #: asked to do — so `make down` does not, and says what it left running.
    def test_the_stop_script_says_the_service_is_still_up(self) -> None:
        script = (ROOT / "scripts" / "dev-down.sh").read_text()
        assert "osint-console.service" in script
        assert "systemctl stop osint-console" in script


#: The board has no bind-mount over the image — `docker-compose.dev.yml` is
#: deliberately not passed here, because the board runs what was built rather
#: than what is on disk. That leaves the build as the only route a backend
#: source change can take, so the start has to take it every time. Without it
#: the README's "run this after every pull" serves the old code indefinitely.
def test_the_start_rebuilds_the_backend() -> None:
    start_body = _serve_script().split("cmd_start() {", 1)[1]
    assert "up -d --build" in start_body
    #: The overlay itself stays out — named in a comment explaining why, never
    #: passed to compose.
    assert "-f docker-compose.dev.yml" not in _serve_script()


#: The stores are pinned to 127.0.0.1 in docker-compose.yml and stay there in
#: every mode. Announcing them as published on the tailnet address describes
#: an exposure that does not exist.
def test_the_start_says_what_is_actually_published() -> None:
    start_body = _serve_script().split("cmd_start() {", 1)[1]
    assert "stores and backend, published" not in start_body
    assert "stores on 127.0.0.1" in start_body


#: The backend is rebuilt by the command; the console is not, and a pull does
#: not touch it. One line for each, and a warning when they have drifted —
#: a single "build" line naming only the console actively suggested the board
#: was current when the backend had moved on.
def test_the_start_names_both_builds_and_notices_when_they_differ() -> None:
    start_body = _serve_script().split("cmd_start() {", 1)[1]
    assert "rev-parse --short HEAD" in start_body
    assert "backend:" in start_body
    assert "console:" in start_body
    assert "serve-build" in start_body


#: A console service running as root leaves a root-owned .next/cache inside a
#: checkout the operator owns, and their next non-root build fails on it. The
#: install is the one place that knows which account that is.
def test_the_install_names_the_account_the_console_runs_as() -> None:
    script = _serve_script()
    assert "SUDO_USER" in script
    install_body = script.split("cmd_install() {", 1)[1]
    assert "installing_account" in install_body
    assert "id -gn" in install_body


#: Reaching for sudo out of habit would otherwise make root the answer, which
#: is the state this exists to avoid. sudo is used on the lines that write.
def test_the_install_refuses_to_run_as_root() -> None:
    install_body = _serve_script().split("cmd_install() {", 1)[1]
    guard = install_body.split('if [ "$account" = "root" ]', 1)
    assert len(guard) == 2
    assert "exit 1" in guard[1][:400]


#: The console alone is half a reboot. The API is published on the tailnet
#: address in this mode, and that address does not exist until tailscaled has
#: configured it — so the containers need a unit that waits for it, and that
#: unit is no use uninstalled.
def test_the_install_puts_the_boot_time_container_start_in_place_too() -> None:
    script = _serve_script()
    assert "osint-stack.service" in script
    install_body = script.split("cmd_install() {", 1)[1]
    assert "render_stack_unit" in install_body
    assert 'systemctl enable --now "$STACK_UNIT"' in install_body


#: Shown before it is written, on the same argument as the console's: a file
#: installed into /etc without being printed is a file nobody reviewed.
def test_the_install_shows_the_boot_time_unit_before_writing_it() -> None:
    install_body = _serve_script().split("cmd_install() {", 1)[1]
    assert install_body.index("render_stack_unit") < install_body.index("sudo install")
    assert install_body.index('cat "$tmp/$STACK_UNIT"') < install_body.index("sudo install")


#: This once asserted that the install loads `.env`'s NEXT_PUBLIC_* keys
#: before rendering the environment file, on the reasoning that the service
#: would otherwise start unable to authenticate. The reasoning was wrong. Next
#: inlines NEXT_PUBLIC_* into the bundle at build time — literal text
#: substitution, not a lookup — so the token is already in the JavaScript the
#: phone downloads, and the copy in the environment file was read by nothing.
#: A test that pins an ordering to a false reason keeps the reason alive.
#:
#: What is true, and worth pinning, is the other half: the build genuinely does
#: need them, and only the build.
def test_the_environment_file_carries_nothing_the_bundle_already_has() -> None:
    script = _serve_script()
    env_body = script.split("render_env_file() {", 1)[1].split("\n}", 1)[0]
    assert "NEXT_PUBLIC_" not in env_body
    assert "OSINT_SERVE_HOST" not in env_body
    assert "NODE_ENV" in env_body


#: Loading them in the install would be loading them for nobody — nothing it
#: renders reads one.
def test_the_install_does_not_load_what_only_the_build_needs() -> None:
    install_body = _serve_script().split("cmd_install() {", 1)[1]
    assert "\n  load_frontend_public_env\n" not in install_body
