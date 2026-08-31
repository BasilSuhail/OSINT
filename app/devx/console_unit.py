"""The console's systemd unit, rendered rather than shipped.

A checked-in unit file cannot know where the repository was cloned, which
address the tailnet handed out, or which port the console was told to use, and
a file with three placeholders to edit by hand is three chances to install a
unit that names a directory that does not exist.

So it is text this module produces and `scripts/serve-up.sh` writes, which is
also what makes it testable: the failures worth catching are all failures of
the text. Starting before the tailnet is up binds an address that does not
exist yet. Not restarting turns one crash into a dark console until somebody
notices. A secret in a unit is published to every account on the machine,
because unit files are world-readable — which is why anything that has to
reach the running process goes in the environment file beside it, which is
not.

That environment file carries no secret today, and saying otherwise was a
mistake worth naming here: `NEXT_PUBLIC_*` values are inlined into the bundle
by the build, so the console's API token travels inside the JavaScript the
phone downloads and a copy in a file on the board is read by nobody. The file
is the route for a value the *running* console reads, and so far that is
`NODE_ENV`.
"""

from __future__ import annotations

UNIT_NAME = "osint-console.service"

#: The containers, brought up once the tailnet address exists. Separate from
#: the console's unit because the two fail differently and are debugged
#: separately: this one is a `docker compose up` that ran or did not, the
#: console is a long-lived process.
STACK_UNIT_NAME = "osint-stack.service"

#: systemd units run with a minimal built-in PATH and never source a login
#: shell, so an inherited PATH cannot be relied on to contain `pnpm`, `docker`
#: or `ip` — this repository has already hit exactly that failure once, in
#: scripts/dev-up.sh, which runs `pnpm dev` through a login shell for the same
#: reason. Named explicitly instead, covering where the documented install
#: (`apt install nodejs && corepack enable`, `get.docker.com`) puts its shims
#: and where Debian puts `ip`.
_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _refuse_unusable(key: str, value: str) -> None:
    """The three value shapes systemd reads as something other than the value.

    Shared by both places a value reaches systemd — the environment file and
    the stack unit's `Environment=` lines — because the parser is the same one
    and so are the corruptions.
    """
    if "\n" in value or "\r" in value:
        raise ValueError(f"{key} contains a newline, which would truncate it")
    if value.endswith("\\"):
        # systemd's EnvironmentFile parser reads a trailing backslash as a
        # line continuation and merges the next line into this value,
        # corrupting both — the same class of failure the newline check
        # above exists to catch.
        raise ValueError(f"{key} ends with a backslash, which systemd reads as a continuation")
    if value.startswith(('"', "'")):
        # A leading quote is quote-processed by systemd too, not just a
        # trailing one — `env_file_text` refuses to add quotes; a value that
        # arrives already carrying one is refused for the same reason.
        raise ValueError(f"{key} starts with a quote character, which systemd strips out")


def env_file_text(env: dict[str, str]) -> str:
    """`KEY=value` lines for systemd's `EnvironmentFile`.

    Unquoted, deliberately: this is read by systemd and not by a shell, so a
    quoted value arrives with the quotes still attached — an origin list that
    starts with a quote character matches no origin at all.
    """
    lines = []
    for key, value in env.items():
        _refuse_unusable(key, value)
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def unit_text(
    *,
    working_dir: str,
    env_file: str,
    bind: str,
    port: int,
    commit_file: str,
    user: str,
    group: str,
) -> str:
    """The service that keeps the console up.

    ## Why it names an account

    A unit with no `User=` runs as root, and the branch's safety argument is a
    network one — the tailnet is the boundary — which says nothing at all about
    local privilege. `next start` needs none of it.

    The practical bite arrives before any attacker does. `next start` writes to
    `.next/cache` in the working directory, so a root service turns a directory
    the operator owns into one they do not, and their next non-root
    `make serve-build` fails on `EACCES` inside their own checkout. The account
    that installs is the account that owns the checkout, which is the account
    this should run as, and `serve-install` knows which one that is.

    ## Which hardening, and which deliberately not

    `NoNewPrivileges=`, `PrivateTmp=`, `PrivateDevices=`, `ProtectKernelTunables=`,
    `ProtectControlGroups=` and `RestrictSUIDSGID=` all hold for a Node process
    that reads a build and answers HTTP.

    `ProtectSystem=full` — /usr, /boot and /etc read-only — and not `strict`,
    which would make the working directory read-only too and stop `next start`
    writing its cache. `ProtectHome=` is left off entirely for the same reason:
    the checkout is under the operator's home, and protecting it would put the
    build out of the service's reach.
    """
    return f"""[Unit]
Description=OSINT console
# `After=` only orders two units that are already starting; it does not pull
# tailscaled into the boot transaction. `Wants=` is what starts it. Together
# they are what actually keeps this unit from binding an address that does
# not exist yet.
After=network-online.target tailscaled.service
Wants=network-online.target tailscaled.service

[Service]
Type=simple
# The account that installed this, which is the account that owns the checkout.
# Without it the service is root, and root writing `.next/cache` is what makes
# the operator's own next build fail on EACCES inside their own directory.
User={user}
Group={group}
WorkingDirectory={working_dir}
# systemd units run with a minimal built-in PATH and never source a login
# shell, so an inherited PATH cannot be relied on to contain `pnpm`.
Environment=PATH={_PATH}
# Beside the unit rather than in it: unit files are world-readable.
EnvironmentFile={env_file}
# Which build is being served, in the journal, so a fix that was pulled and
# not rebuilt is a line to read rather than a mystery.
ExecStartPre=/bin/sh -c 'echo "console build: $(cat {commit_file} 2>/dev/null || echo unknown)"'
ExecStart=/usr/bin/env pnpm exec next start -H {bind} -p {port}
Restart=always
RestartSec=5
# A build server answering HTTP needs none of this, so it does not get it.
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
# `full`, not `strict`: strict makes the working directory read-only too, and
# `next start` writes .next/cache. ProtectHome= is absent for the same reason —
# the checkout lives under the operator's home.
ProtectSystem=full

[Install]
WantedBy=multi-user.target
"""


def stack_unit_text(
    *,
    working_dir: str,
    bind: str,
    environment: dict[str, str],
) -> str:
    """The unit that brings the containers up once the tailnet address exists.

    ## The failure this exists for

    `API_BIND` in serve mode is the board's tailnet address. Every earlier mode
    bound `127.0.0.1` or `0.0.0.0`, both of which exist the moment the kernel
    is up; `100.x.y.z` exists only once tailscaled has configured its
    interface. `docker.service` and `tailscaled.service` are ordered against
    each other by nothing, so on a reboot dockerd can restore the `api`
    container first, the port allocation fails with `bind: cannot assign
    requested address`, and — because a *start* failure is not a container
    *exit* — `restart: unless-stopped` never fires. The container stays down.

    The console recovers on its own (`Restart=always`), so the symptom is a
    page that loads with every panel empty: indistinguishable, from the phone,
    from a backend that is broken.

    ## Why a unit that waits, rather than a drop-in that orders

    A `docker.service.d` drop-in saying `After=tailscaled.service` is four
    lines and was the first thing considered. It was not enough. tailscaled is
    `Type=notify` and reports ready when the *daemon* is up, which is before it
    has reached the control plane and configured an address on the interface —
    so the drop-in narrows the race without closing it, and a race that fires
    rarely is harder to diagnose than one that fires every time. It would also
    put every other container on the board behind tailscaled, which is a cost
    paid by workloads that never asked.

    So this waits for the address itself, and then reconciles. Waiting is the
    only check that is actually true at the moment it passes: the address is on
    an interface, therefore a bind will succeed. It also repairs the case where
    dockerd already tried and failed, which ordering alone cannot — `up -d`
    starts a container that exists and is not running.

    ## Why this one does stay root

    The console's unit names an account; this one does not, and should not. Its
    whole body is a `docker compose` call, and access to the Docker socket is
    root-equivalent by construction — an unprivileged account that could make
    it would be root wearing a different name. It writes nothing into the
    checkout, so it does not carry the ownership problem that made root wrong
    for the console.

    `Before=` the console rather than the console waiting on its own: the
    console's same-origin proxy calls the API on this address, and ordering it
    after this unit means it does not start until that upstream is available.
    """
    lines = []
    for key, value in environment.items():
        _refuse_unusable(key, value)
        if '"' in value:
            # `Environment="KEY=value"` is the form that survives a value with
            # a space in it, and an embedded double quote ends the assignment
            # early — the rest of the value becomes a second, malformed one.
            raise ValueError(f"{key} contains a double quote, which ends the assignment early")
        lines.append(f'Environment="{key}={value}"')
    rendered = "\n".join(lines)

    return f"""[Unit]
Description=OSINT containers, once the tailnet address exists
# `After=` orders; `Wants=` is what pulls them into the boot transaction. Both
# are needed, and neither is sufficient on its own — see ExecStartPre.
After=docker.service tailscaled.service network-online.target
Wants=docker.service tailscaled.service network-online.target
# The console proxies browser API calls to this address. Ordered behind this,
# it starts with a live upstream instead of an empty page.
Before={UNIT_NAME}

[Service]
# One reconciliation, not a supervised process: the containers supervise
# themselves once they are started, and `restart: unless-stopped` works
# perfectly well for every failure that is an exit rather than a failed start.
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={working_dir}
Environment=PATH={_PATH}
{rendered}
# The one check that is true at the moment it passes: tailscaled reports ready
# before it has configured an address, so `After=tailscaled.service` is not
# the same question as "can this address be bound". No interface is named —
# the address being on any of them is the whole precondition. No shell
# variable either: systemd expands `$word` inside ExecStart lines before sh
# ever sees it, so a loop counter would arrive empty.
ExecStartPre=/bin/sh -c 'until ip -4 -o addr show | grep -q " {bind}/"; do sleep 2; done'
ExecStart=/usr/bin/env docker compose up -d
# The wait above has no bound of its own. This is the bound: five minutes, and
# then a journal line saying the start timed out, which is the truth. Trying
# again half a minute later covers a tailnet that came up slowly.
TimeoutStartSec=300
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
"""
