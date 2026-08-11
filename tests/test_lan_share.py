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


@pytest.mark.parametrize("address", ["", "   ", "not-an-ip", "999.1.1.1", "::1"])
def test_share_refuses_an_address_that_is_not_a_usable_ipv4(address: str) -> None:
    """A wrong address fails now, with a name, rather than as an empty console.

    IPv6 is refused too: the compose port mapping and the bundle URL would both
    need bracket syntax, and nothing in the stack has been tried that way.
    """
    with pytest.raises(ShareAddressError):
        share_env(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0"])
def test_share_refuses_an_address_no_guest_could_use(address: str) -> None:
    with pytest.raises(ShareAddressError):
        share_env(address)


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
    """
    script = DEV_UP.read_text()
    assert 'printf \'%s %s\' "$FRONTEND_BIND" "${NEXT_PUBLIC_API_URL:-}"' in script
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
