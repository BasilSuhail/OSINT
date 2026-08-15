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

## Why the flag is never written to a file

The failure this exists to prevent is not "cannot share", it is "still sharing
somewhere else". Share mode is a run-time environment variable, so a stack
opened at home and restarted on another network comes back closed with no file
to remember to change back.

## Why four settings, not one

A guest device needs all four to agree, and any one of them alone produces a
console that looks broken rather than one that says why:

- `API_BIND` — the published bind address. Wrong, and the guest reaches
  nothing.
- `API_CORS_ORIGINS` — the origin allow-list. Wrong, and the guest's browser
  makes the request, then discards the answer at the preflight.
- `NEXT_PUBLIC_API_URL` — compiled into the bundle the guest downloads, so it
  must name an address the *guest* can resolve. The default
  `http://localhost:8000`, in a guest's browser, is the guest's own machine.
- `LAN_SHARE_HOST` → `allowedDevOrigins` — `next dev` refuses its own
  `/_next/*` dev resources for any host that is not localhost. Missing, and the
  guest gets a page shell, a websocket retrying forever, and a map that never
  initialises (#930).

The fourth was missed the first time, which is the argument for deriving them
together: one address in, everything that depends on it out.

## Why no credential

Share mode adds none. The guest loads the frontend, so `NEXT_PUBLIC_API_TOKEN`
travels to them inside the bundle; a secret every visitor is handed is not one.
Network scope is the control being asked for, and stating that is better than
implying a protection that is not there.

    python -m app.devx.lan_share locked     # print shell exports for eval
    python -m app.devx.lan_share share      # detect the address, then the same
"""

from __future__ import annotations

import ipaddress
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
        # and the bundle URL both need bracket syntax, and neither has been
        # tried that way. A trailing `:port` lands here too, and the port is
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
    api_port: int = DEFAULT_API_PORT,
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
        "NEXT_PUBLIC_API_URL": f"http://{ip}:{api_port}",
        "API_CORS_ORIGINS": ",".join(origins),
        # `next dev` refuses its own /_next/* dev resources for any host that is
        # not localhost, which reached the guest as a page shell with a dead
        # websocket and a map that never initialised (#930). Bare host: the
        # config wants no scheme and no port.
        "LAN_SHARE_HOST": ip,
        "LAN_SHARE_URL": guest_origin,
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

    if mode != "share":
        print(f"usage: python -m app.devx.lan_share [locked|share] (got {mode!r})", file=sys.stderr)
        return 2

    #: The same setting `make env` derives NEXT_PUBLIC_API_URL from (#964).
    #: Share mode used to ignore it and overwrite that value with the detected
    #: address, so pinning a host and then sharing silently discarded the
    #: choice — two commands in one project reading one setting differently
    #: (#974). Detection is now the fallback, not the rule.
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
            api_port=int(_env_port("API_PORT", DEFAULT_API_PORT)),
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
