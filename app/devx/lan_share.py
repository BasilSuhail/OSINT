"""Who, on the network, may reach this stack (#928).

`make up` published the API and the dashboard on every interface. On a home
network that is a feature — a second device can open the console. On any
network the operator does not control it hands over the data and
`POST /brain/ask`, which spends local model inference per call. #824 closed the
stores and added the optional shared secret; the two ports a browser uses were
left open.

So: closed by default, open when asked, and never open by accident.

    make up        # 127.0.0.1 only, nothing on the network can reach it
    make share     # reachable from the local network, prints the guest URL
    make serve     # reachable from the tailnet, and still there after a reboot

## Why the flag is never written to a file

The failure this exists to prevent is not "cannot share", it is "still sharing
somewhere else". Share mode is a run-time environment variable, so a stack
opened at home and restarted on another network comes back closed with no file
to remember to change back.

## Why these settings travel together

A guest device needs all of them to agree, and one wrong value produces a
console that looks broken rather than one that says why:

- `API_BIND` — the published bind address. Wrong, and the guest reaches
  nothing.
- `API_CORS_ORIGINS` — the origin allow-list. Wrong, and the guest's browser
  makes the request, then discards the answer at the preflight.
- `NEXT_PUBLIC_API_URL` — the browser uses the same-origin `/api` path, which
  Next proxies to the local API. An absolute HTTP URL would be blocked when the
  frontend is served over HTTPS.
- `API_PROXY_TARGET` — the upstream Next calls behind `/api`. Development can
  use loopback; serve mode must use the API's tailnet bind because that is the
  only address where the board publishes it.
- `LAN_SHARE_HOST` → `allowedDevOrigins` — `next dev` refuses its own
  `/_next/*` dev resources for any host that is not localhost. Missing, and the
  guest gets a page shell, a websocket retrying forever, and a map that never
  initialises (#930).

The dev-host setting was missed the first time, which is the argument for
deriving them together: one address in, everything that depends on it out.

## Why no credential

Share mode adds none. The guest loads the frontend, so `NEXT_PUBLIC_API_TOKEN`
travels to them inside the bundle; a secret every visitor is handed is not one.
Network scope is the control being asked for, and stating that is better than
implying a protection that is not there. Serve mode is the exception: it
requires `API_AUTH_TOKEN` set, and does not carry the token to just anyone —
the reasoning that makes a bundled secret pointless for a guest on the home
wifi does not apply when the only devices that can even reach the board are
the operator's own, admitted to the tailnet one at a time by the operator.

## Two modes, two protections

Share and serve are not the same guarantee reached by different addresses.
Share mode's protection *is* the bind address — a guest reaches the console
because, and only because, the process is listening where their packets
arrive. Take the address away and the protection is gone with it, which is
the whole argument, above, for never writing it to a file: the one thing
standing between "closed" and "open" must not survive past the run that set
it.

Serve mode's protection is the tailnet itself. A device Tailscale has not
admitted cannot resolve the board's name or route to its address, whatever
the board happens to be bound to — the network refuses the packet before the
bind address is ever consulted. Remembering "this machine serves" does not
widen who can reach it; only the operator, from the Tailscale admin console,
does that. That is what makes it safe for serve mode to survive a reboot
where share mode may not.

    python -m app.devx.lan_share locked     # print shell exports for eval
    python -m app.devx.lan_share share      # detect the address, then the same
    python -m app.devx.lan_share serve      # read the tailnet identity, then the same
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import sys

#: Reachable only from this machine.
LOOPBACK: str = "127.0.0.1"

#: Reachable from whatever network the machine is attached to.
ALL_INTERFACES: str = "0.0.0.0"

#: Used when nothing is configured. Mirrors the API's own default so that
#: sharing never silently narrows what already worked.
DEFAULT_CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

DEFAULT_API_PORT: int = 8000
DEFAULT_FRONTEND_PORT: int = 3000


class ShareAddressError(ValueError):
    """The address share mode would publish is not one a guest could use."""


def locked_env() -> dict[str, str]:
    """Bind addresses for the closed default.

    Only the binds. Emitting an origin list or an API URL here would override
    whatever is configured in `.env` to say what the defaults already say.
    """
    return {"API_BIND": LOOPBACK, "FRONTEND_BIND": LOOPBACK}


#: One hostname label: letters, digits and inner hyphens, up to 63 characters.
_LABEL = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

#: Names that mean "this machine". On a guest device each of them names the
#: guest, so sharing on one publishes a console nobody else can load.
_MEANS_THIS_MACHINE = frozenset({"localhost", "localhost.localdomain"})


def _validated(address: str) -> str:
    """An address or name a guest could actually put in a browser.

    A name is accepted as well as an address (#974). The detected address is
    private, so reaching the console from anywhere else means naming the host
    some other way — which is the entire purpose of pinning one.
    """
    candidate = address.strip()
    if not candidate:
        raise ShareAddressError("no address to share on (is this machine on a network?)")
    if any(character.isspace() for character in candidate):
        raise ShareAddressError(f"{candidate!r} contains whitespace")
    if "/" in candidate:
        raise ShareAddressError(f"{candidate!r} looks like a URL; give a bare host")
    if ":" in candidate:
        # IPv6 is refused rather than half-supported: the compose port mapping
        # and guest URL both need bracket syntax, and neither has been tried
        # that way. A trailing `:port` lands here too; the frontend port is
        # supplied separately.
        raise ShareAddressError(f"{candidate!r} must carry no port and no colon")

    labels = candidate.split(".")
    if all(label.isdigit() for label in labels if label):
        # Somebody meant an address and mistyped it. No hostname is spelled this
        # way, so reading it as one would turn a typo into a name that never
        # resolves and an empty console with no explanation.
        try:
            parsed = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError as exc:
            raise ShareAddressError(f"{candidate!r} is not an IPv4 address") from exc
        if parsed.is_loopback or parsed.is_unspecified:
            raise ShareAddressError(f"{candidate} is not reachable from another device")
        return candidate

    if candidate.lower() in _MEANS_THIS_MACHINE:
        raise ShareAddressError(f"{candidate} is not reachable from another device")
    if not all(_LABEL.match(label) for label in labels):
        raise ShareAddressError(f"{candidate!r} is not a usable host name")
    return candidate


def share_env(
    address: str,
    *,
    frontend_port: int = DEFAULT_FRONTEND_PORT,
    cors_origins: str = "",
    also_reachable_at: tuple[str, ...] = (),
) -> dict[str, str]:
    """Every setting that has to change together, derived from one address.

    ``also_reachable_at`` names the other ways in which this machine can be
    reached — in practice the detected local address, when the host was pinned
    to something else (#974). They reach the origin allow-list and nothing else,
    so pinning never takes away the network that already worked. One that is
    unusable is dropped rather than fatal: a pin given by hand must not fail
    because detection did.
    """
    ip = _validated(address)
    guest_origin = f"http://{ip}:{frontend_port}"

    extra: list[str] = []
    for other in also_reachable_at:
        try:
            extra.append(f"http://{_validated(other)}:{frontend_port}")
        except ShareAddressError:
            continue

    configured = [o.strip() for o in (cors_origins or DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
    origins: list[str] = []
    for origin in [*configured, guest_origin, *extra]:
        if origin not in origins:
            origins.append(origin)

    return {
        "API_BIND": ALL_INTERFACES,
        "FRONTEND_BIND": ALL_INTERFACES,
        # Browser calls stay on the frontend origin. Next proxies this path to
        # the local API, so a guest never needs to resolve a second origin and
        # an HTTPS frontend never attempts blocked HTTP mixed content (#1034).
        "NEXT_PUBLIC_API_URL": "/api",
        "API_CORS_ORIGINS": ",".join(origins),
        # `next dev` refuses its own /_next/* dev resources for any host that is
        # not localhost, which reached the guest as a page shell with a dead
        # websocket and a map that never initialised (#930). Bare host: the
        # config wants no scheme and no port.
        "LAN_SHARE_HOST": ip,
        "LAN_SHARE_URL": guest_origin,
    }


#: What Tailscale hands out. An address outside it is another network — in
#: practice the home wifi, which is the exposure share mode announces and this
#: mode does not.
TAILNET_RANGE = ipaddress.ip_network("100.64.0.0/10")


class ServeRefused(RuntimeError):  # noqa: N818 - named for what it does, not what it is
    """Serve mode will not start, and the message says what to do about it."""


def require_api_token(api_token: str) -> None:
    """The one precondition of serve mode that costs nothing to check.

    Split out of `serve_env` so the command-line path can ask it *before*
    `tailnet_identity` shells out to Tailscale. A board with Tailscale down and
    an empty token used to be told only about Tailscale, fix that, run again,
    and meet the second refusal — two round trips for two facts that were both
    knowable at the start. This one needs no subprocess, so it goes first.
    """
    if not api_token.strip():
        raise ServeRefused(
            "serve mode needs API_AUTH_TOKEN set — it is the only thing between "
            "a device on the tailnet and an endpoint that spends model inference"
        )


#: How long the tailnet probe waits, in seconds.
#:
#: Short on purpose, and shorter than it was. A tailnet that is up answers
#: `tailscale status --json` in milliseconds, so the extra patience buys
#: nothing from the case it looks like it is for. What it does buy is a longer
#: window in which an aborted parent leaves the child running — see
#: `_tailscale_status`. The failure being waited on here is not a slow tailnet,
#: it is a CLI with no daemon to answer it, and waiting longer never turns that
#: into an answer. Same value as `_run` below, which shells out for the same
#: kind of question.
TAILSCALE_STATUS_TIMEOUT: int = 5


def require_linux() -> None:
    """Serve mode configures a board, and boards here are Linux.

    Checked before anything else in the mode — before the token, and above all
    before the tailnet probe — because a platform that cannot use the answer
    has no business asking the question. Everything serve mode derives is for a
    machine with systemd: a bind on a tailnet interface, a unit file, a service
    that survives a reboot. `make serve-install` has always refused where there
    is no systemd; the module did not, so the mode stayed reachable by hand and
    the probe with it.

    Only serve mode. Locked and share are the laptop's modes — `scripts/dev-up.sh`
    derives locked on every `make up` — and a guard reaching them would stop the
    stack starting on the machine it is developed on.
    """
    if not sys.platform.startswith("linux"):
        raise ServeRefused(
            f"serve mode configures a board: it binds a tailnet interface and installs "
            f"systemd units, and this machine is {sys.platform}. Run it on the board "
            f"itself — `make up` and `make share` are this machine's modes"
        )


def _tailscale_status() -> dict:
    """`tailscale status --json`, parsed. Seam for the tests.

    This shells out, which is why `require_linux` and `require_api_token` are
    both asked before it — and why the platform guard, not a cleanup handler,
    is what closes the failure below.

    A probe started here once outlived the process that started it. The parent
    was aborted rather than exiting, so nothing Python could have registered
    ran: no `finally`, no `atexit` — neither fires when the parent is killed —
    and the child was reparented to init. It should still have exited at the
    timeout, but the host it ran on had Tailscale installed with its network
    extension unapproved, leaving the CLI no daemon to talk to and a retry loop
    rather than a failure. It ran for days and reached tens of gigabytes of
    memory before anyone noticed.

    That is a property of every subprocess call and cannot be fixed from inside
    the parent. What can be fixed is the path: the host in question was not a
    board and could not have used the answer, and now it is refused before this
    is reached. The timeout is short for the same reason — it bounds the window
    rather than the tailnet.
    """
    try:
        raw = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=TAILSCALE_STATUS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServeRefused("tailscale is not installed or not running") from exc
    if raw.returncode != 0:
        raise ServeRefused("tailscale is installed but not up — run `tailscale up`")
    try:
        return json.loads(raw.stdout)
    except json.JSONDecodeError as exc:
        raise ServeRefused("tailscale answered something this cannot read") from exc


def tailnet_identity() -> tuple[str, str]:
    """This board's name and address on the tailnet.

    The name is what the phone resolves and the address is what the API binds,
    and they are read together so a console can never be built naming one
    machine and bound to another.
    """
    status = _tailscale_status()
    myself = status.get("Self") or {}
    host = str(myself.get("DNSName") or "").strip().rstrip(".")
    addresses = [str(a) for a in (myself.get("TailscaleIPs") or []) if ":" not in str(a)]
    if not host or not addresses:
        raise ServeRefused("the tailnet did not say what this machine is called — is it up?")
    _require_magic_dns(status, host)
    return host, addresses[0]


def _require_magic_dns(status: dict, host: str) -> None:
    """Refuse unless the tailnet will resolve the private HTTPS name.

    `Self.DNSName` is populated whether or not MagicDNS is switched on — it is
    the name the node *would* answer to. With MagicDNS off, nothing resolves
    it, and every step of serve mode still succeeds: the build finishes, the
    unit installs, the service starts, and the phone gets NXDOMAIN after the
    reboot with nothing anywhere saying why.

    That makes this the worst precondition in the mode to leave unchecked. A
    manifest on raw HTTP is not installable in current browsers; Tailscale
    Serve needs this name to provision the secure origin. It is checked before
    the name is handed back, and the message names the setting and the command
    to rerun.

    A tailnet that reports nothing about MagicDNS is refused too, rather than
    assumed good. Refusing on a field that did not arrive costs the operator
    one look at the admin console; assuming it costs a build, a reboot and a
    console that loads nothing.
    """
    tailnet = status.get("CurrentTailnet") or {}
    if tailnet.get("MagicDNSEnabled"):
        return
    raise ServeRefused(
        f"MagicDNS is off for this tailnet, so nothing can resolve {host} — the phone "
        "would get a name that does not exist. Turn MagicDNS on in the Tailscale admin "
        "console (DNS → MagicDNS), then rerun the serve command"
    )


def serve_env(
    host: str,
    address: str,
    *,
    api_port: int = DEFAULT_API_PORT,
    frontend_port: int = DEFAULT_FRONTEND_PORT,
    cors_origins: str = "",
    api_token: str = "",
) -> dict[str, str]:
    """Every setting a served console needs, derived from the tailnet identity.

    Two arguments rather than one because the two answers differ and both are
    load-bearing: the phone opens the MagicDNS name, while the API proxy must
    name the interface where the board actually publishes the backend.
    """
    require_api_token(api_token)
    name = _validated(host)
    try:
        bind = ipaddress.IPv4Address(address.strip())
    except ipaddress.AddressValueError as exc:
        raise ServeRefused(f"{address!r} is not an IPv4 address") from exc
    if bind not in TAILNET_RANGE:
        raise ServeRefused(f"{bind} is not a tailnet address — serve mode binds the tailnet only")

    origin = f"https://{name}"
    configured = [o.strip() for o in (cors_origins or DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
    origins: list[str] = []
    for candidate in [*configured, origin]:
        if candidate not in origins:
            origins.append(candidate)

    return {
        "API_BIND": str(bind),
        # Tailscale Serve terminates HTTPS and is only able to proxy to
        # loopback. Keeping Next there also removes its raw HTTP port from the
        # tailnet; the phone reaches the secure origin instead (#1034).
        "FRONTEND_BIND": LOOPBACK,
        "NEXT_PUBLIC_API_URL": "/api",
        "API_PROXY_TARGET": f"http://{bind}:{api_port}",
        "API_CORS_ORIGINS": ",".join(origins),
        "OSINT_SERVE_HOST": name,
        "OSINT_SERVE_URL": origin,
    }


def detect_lan_ip() -> str:
    """This machine's address on the network it is currently attached to.

    `ipconfig getifaddr` on the interface carrying the default route is the
    macOS answer and the accurate one: it follows a move from wifi to ethernet
    without being told. The socket fallback covers Linux — no packet is sent,
    the connect only asks the routing table which source address it would use.
    """
    interface = _default_route_interface()
    if interface:
        found = _run(["ipconfig", "getifaddr", interface])
        if found:
            return found

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1, routed nowhere.
            return probe.getsockname()[0]
        except OSError as exc:
            raise ShareAddressError("could not work out this machine's network address") from exc


def _default_route_interface() -> str:
    output = _run(["route", "-n", "get", "default"])
    for line in output.splitlines():
        name, _, value = line.partition(":")
        if name.strip() == "interface":
            return value.strip()
    return ""


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def render_exports(env: dict[str, str]) -> str:
    """Shell `export` lines, quoted, for the caller to `eval`."""
    return "".join(f"export {key}={shlex.quote(value)}\n" for key, value in env.items())


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = args[0] if args else "locked"

    if mode == "locked":
        sys.stdout.write(render_exports(locked_env()))
        return 0

    if mode == "serve":
        try:
            #: Cheapest refusal first, and in that order: this one reads a
            #: constant, the next an environment variable, the last shells out
            #: to Tailscale. Asked the other way round, a board with more than
            #: one of them wrong gets told about one per attempt — and a
            #: machine that is not a board at all spawns a probe whose answer
            #: it could never have used.
            require_linux()
            require_api_token(_env("API_AUTH_TOKEN"))
            host, address = tailnet_identity()
            env = serve_env(
                # Tailscale provisions HTTPS only for this node's MagicDNS
                # name. OSINT_PUBLIC_HOST remains a share-mode override; using
                # it here would print a secure URL with no certificate.
                host,
                address,
                api_port=int(_env_port("API_PORT", DEFAULT_API_PORT)),
                frontend_port=int(_env_port("FRONTEND_PORT", DEFAULT_FRONTEND_PORT)),
                cors_origins=_env("API_CORS_ORIGINS"),
                api_token=_env("API_AUTH_TOKEN"),
            )
        except (ServeRefused, ShareAddressError) as exc:
            #: The caller evals this output, so a failure must print no exports.
            print(f"cannot serve: {exc}", file=sys.stderr)
            return 1
        sys.stdout.write(render_exports(env))
        return 0

    if mode != "share":
        print(
            f"usage: python -m app.devx.lan_share [locked|share|serve] (got {mode!r})",
            file=sys.stderr,
        )
        return 2

    #: A pinned host is the address printed for a guest and allowed through the
    #: dev server. Detection is the fallback, not the rule (#974).
    pinned = _env("OSINT_PUBLIC_HOST").strip()
    detected = ""
    try:
        detected = detect_lan_ip()
    except ShareAddressError:
        # Only fatal when there is no pin to fall back on, handled below.
        detected = ""

    try:
        env = share_env(
            pinned or detected,
            frontend_port=int(_env_port("FRONTEND_PORT", DEFAULT_FRONTEND_PORT)),
            cors_origins=_env("API_CORS_ORIGINS"),
            also_reachable_at=(detected,) if pinned else (),
        )
    except ShareAddressError as exc:
        # The caller evals this output, so a failure must not print exports.
        print(f"cannot share: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(render_exports(env))
    return 0


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _env_port(name: str, fallback: int) -> int:
    raw = _env(name).strip()
    return int(raw) if raw.isdigit() else fallback


if __name__ == "__main__":
    sys.exit(main())
