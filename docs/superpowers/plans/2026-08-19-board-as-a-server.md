# The board as a server — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A board that boots into a built console, reachable from a phone on the tailnet, with nothing typed and no port opened.

**Architecture:** A third mode in `app/devx/lan_share.py` — `serve` — derives the same shape `locked` and `share` derive, from the tailnet hostname and address rather than a LAN address. A small new module renders a systemd unit and its environment file as text. A shell script and three `make` targets build the console, install the unit, and start the stack in that mode. The backend needs nothing: compose already restarts itself at boot.

**Tech Stack:** Python 3.14 (stdlib only for `app/devx/*`), pytest, bash, systemd, Next.js 15 (`next start`), pnpm, Tailscale.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-19-board-as-a-server-design.md`.
- Branch already exists and holds the spec commit: `feat/board-as-a-server`. Do not branch again.
- Repository is PUBLIC. No personal names, no institution, no course/degree/assessment vocabulary, no contact details — in code, comments, commit messages or PR text. Write the role: "the operator", "the reader", "the maintainer".
- **No real network is a repository's to record.** `tests/test_lan_share.py` says this outright and uses the RFC 5737 documentation range for addresses. Tailnet addresses in tests must be invented values inside `100.64.0.0/10`, and tailnet hostnames must be obviously fictional (`board.example-tailnet.ts.net`). Never a real one.
- Commit messages carry no attribution trailers: no `Co-Authored-By`, no "generated with" line.
- `app/devx/lan_share.py` imports nothing but the standard library, deliberately — `scripts/dev-up.sh` runs it with bare `python3` on machines that have no virtualenv yet. Anything new in `app/devx/` keeps that rule. No third-party imports, no imports from the rest of `app/`.
- Use the repo venv by absolute path for tooling: `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/python`. Never bare `python`, never bare `timeout`. pnpm, never npm.
- CI runs `ruff check app/ tests/` and `ruff format --check app/ tests/`. Both must pass.
- Comment style: `#:` above Python definitions, `//:` in TypeScript bodies. `lan_share.py` and its test file both open with a long docstring explaining *why* the module exists. Match that density — a bare function added there reads as foreign.
- Run only the tests a task touches. Full suites belong to CI.
- Known local noise, not yours to fix: `tests/test_presence_aircraft.py` and `tests/test_presence_watchlist.py` fail in this working copy because an untracked `data/watchlist.json` is picked up by a fallback path. Tests also need `API_AUTH_TOKEN=""` exported or the local `.env` token 401s them.

## Files

- Modify `app/devx/lan_share.py` — `serve_env()`, `ServeRefused`, `tailnet_identity()`, `serve` wired into `main()`.
- Create `app/devx/console_unit.py` — renders the systemd unit and its environment file as text. Stdlib only.
- Create `scripts/serve-up.sh` — build, install, start.
- Modify `Makefile` — `serve-build`, `serve-install`, `serve`.
- Modify `tests/test_lan_share.py` — serve-mode derivation and refusals.
- Create `tests/test_console_unit.py` — the rendered unit and env file.
- Modify `README.md` — a "Run it as a server" block.

**Why a separate script rather than a mode inside `dev-up.sh`.** `dev-up.sh` supervises `next dev` by hand: pid files, a mode signature, a sweep for the child `next-server`, a restart when the bind changed. Under systemd all of that is the service manager's job, and a script that does both fights it. `serve-up.sh` builds, installs and hands over; systemd runs the console.

---

### Task 1: Serve mode

**Files:**
- Modify: `app/devx/lan_share.py` (module docstring, then beside `share_env`, then `main()` at line ~230)
- Test: `tests/test_lan_share.py`

**Interfaces:**
- Produces:
  - `TAILNET_RANGE = ipaddress.ip_network("100.64.0.0/10")`
  - `class ServeRefused(RuntimeError)`
  - `tailnet_identity() -> tuple[str, str]` — `(hostname, address)` from `tailscale status --json`, raising `ServeRefused` when Tailscale is absent, down, or answers without them
  - `serve_env(host: str, address: str, *, api_port: int = DEFAULT_API_PORT, frontend_port: int = DEFAULT_FRONTEND_PORT, cors_origins: str = "", api_token: str = "") -> dict[str, str]` returning keys `API_BIND`, `FRONTEND_BIND`, `NEXT_PUBLIC_API_URL`, `API_CORS_ORIGINS`, `OSINT_SERVE_HOST`, `OSINT_SERVE_URL`
  - `python -m app.devx.lan_share serve` printing the same `export` lines the other modes print

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lan_share.py`. Read the top of that file first — its docstring explains why addresses come from a documentation range, and the same reasoning governs these:

```python
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
    STATUS = {
        "Self": {
            "DNSName": "board.example-tailnet.ts.net.",
            "TailscaleIPs": ["100.100.100.100", "fd7a:1::1"],
        }
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
```

Add `ServeRefused`, `serve_env` to the existing `from app.devx.lan_share import (...)` block at the top of the file, and `from app.devx import lan_share` alongside it (the monkeypatching tests need the module object).

- [ ] **Step 2: Run them and watch them fail**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_lan_share.py -k "Serve or Tailnet" -v`
Expected: FAIL — `ImportError` on `ServeRefused`.

- [ ] **Step 3: Extend the module docstring**

`lan_share.py` opens by explaining closed-by-default and, under "Why the flag is never written to a file", argues share mode must not persist. Serve mode contradicts that, and the contradiction has to be answered where a reader meets it. Add to the docstring, in its voice:

- the third line of the usage block: `make serve   # reachable from the tailnet, and still there after a reboot`
- a short section saying the two modes are protected by different things. Share's protection is the bind address, so taking the address away takes the protection away — which is why it must not persist. Serve's protection is the tailnet: a device that is not on it cannot resolve or route to the board whatever the board is bound to, so remembering the mode does not widen the audience.
- one line under "Why no credential": serve mode requires `API_AUTH_TOKEN`, and why the same reasoning that makes it pointless for share (the bundle carries it to any guest) does not apply when the guests are the operator's own devices.

- [ ] **Step 4: Write the implementation**

Beside `share_env`, stdlib only:

```python
#: What Tailscale hands out. An address outside it is another network — in
#: practice the home wifi, which is the exposure share mode announces and this
#: mode does not.
TAILNET_RANGE = ipaddress.ip_network("100.64.0.0/10")


class ServeRefused(RuntimeError):
    """Serve mode will not start, and the message says what to do about it."""


def _tailscale_status() -> dict:
    """`tailscale status --json`, parsed. Seam for the tests."""
    try:
        raw = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
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
    return host, addresses[0]


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
    load-bearing: the bundle must name what the *phone* resolves, and the bind
    must name the interface the tailnet is on.
    """
    if not api_token.strip():
        raise ServeRefused(
            "serve mode needs API_AUTH_TOKEN set — it is the only thing between "
            "a device on the tailnet and an endpoint that spends model inference"
        )
    name = _validated(host)
    try:
        bind = ipaddress.IPv4Address(address.strip())
    except ipaddress.AddressValueError as exc:
        raise ServeRefused(f"{address!r} is not an IPv4 address") from exc
    if bind not in TAILNET_RANGE:
        raise ServeRefused(f"{bind} is not a tailnet address — serve mode binds the tailnet only")

    origin = f"http://{name}:{frontend_port}"
    configured = [o.strip() for o in (cors_origins or DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
    origins: list[str] = []
    for candidate in [*configured, origin]:
        if candidate not in origins:
            origins.append(candidate)

    return {
        "API_BIND": str(bind),
        "FRONTEND_BIND": str(bind),
        "NEXT_PUBLIC_API_URL": f"http://{name}:{api_port}",
        "API_CORS_ORIGINS": ",".join(origins),
        "OSINT_SERVE_HOST": name,
        "OSINT_SERVE_URL": origin,
    }
```

Add `import json` and `import subprocess` to the imports if `subprocess` is not already there (it is, for `_run`).

- [ ] **Step 5: Wire the mode into `main()`**

`main()` currently accepts `locked` and `share` and rejects everything else. Add the branch before the `!= "share"` rejection, and update the usage string to `[locked|share|serve]`:

```python
    if mode == "serve":
        try:
            pinned = _env("OSINT_PUBLIC_HOST").strip()
            host, address = tailnet_identity()
            env = serve_env(
                pinned or host,
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
```

`OSINT_PUBLIC_HOST` overrides the detected name and never the address: pinning is about what the phone types, and the interface to bind is not a matter of preference.

- [ ] **Step 6: Run the tests**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_lan_share.py -v`
Expected: PASS — the new tests and every test already in the file. The existing `locked` and `share` tests must not have been touched.

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Step 8: Commit**

```bash
git add app/devx/lan_share.py tests/test_lan_share.py
git commit -m "feat(devx): a third network mode, for a board that stays reachable"
```

---

### Task 2: The unit, as text

**Files:**
- Create: `app/devx/console_unit.py`
- Test: `tests/test_console_unit.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime. The dict `serve_env()` returns is what `env_file_text` is given.
- Produces:
  - `UNIT_NAME = "osint-console.service"`
  - `env_file_text(env: dict[str, str]) -> str`
  - `unit_text(*, working_dir: str, env_file: str, bind: str, port: int, commit_file: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_console_unit.py`:

```python
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
        working_dir="/srv/osint/osint-frontend",
        env_file="/etc/osint-console.env",
        bind="100.100.100.100",
        port=3000,
        commit_file="/srv/osint/osint-frontend/.next/BUILD_COMMIT",
    )


def test_the_unit_is_named_for_what_it_runs() -> None:
    assert UNIT_NAME == "osint-console.service"


#: The bind address does not exist until the tailnet is up. Starting before
#: that is the one failure that happens at boot and not when tried by hand,
#: which is the hardest kind to find.
def test_it_waits_for_the_network_and_the_tailnet() -> None:
    unit = _unit()
    assert "After=network-online.target tailscaled.service" in unit
    assert "Wants=network-online.target" in unit


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


#: The unit file is world-readable. The token belongs in the environment file
#: beside it, which is not.
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_console_unit.py -v`
Expected: FAIL — `ModuleNotFoundError: app.devx.console_unit`.

- [ ] **Step 3: Write the module**

Create `app/devx/console_unit.py`. Standard library only, like its neighbour:

```python
"""The console's systemd unit, rendered rather than shipped.

A checked-in unit file cannot know where the repository was cloned, which
address the tailnet handed out, or which port the console was told to use, and
a file with three placeholders to edit by hand is three chances to install a
unit that names a directory that does not exist.

So it is text this module produces and `scripts/serve-up.sh` writes, which is
also what makes it testable: the failures worth catching are all failures of
the text. Starting before the tailnet is up binds an address that does not
exist yet. Not restarting turns one crash into a dark console until somebody
notices. Writing the token into the unit publishes it to every account on the
machine, because unit files are world-readable and the environment file beside
them is not.
"""

from __future__ import annotations

UNIT_NAME = "osint-console.service"


def env_file_text(env: dict[str, str]) -> str:
    """`KEY=value` lines for systemd's `EnvironmentFile`.

    Unquoted, deliberately: this is read by systemd and not by a shell, so a
    quoted value arrives with the quotes still attached — an origin list that
    starts with a quote character matches no origin at all.
    """
    lines = []
    for key, value in env.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} contains a newline, which would truncate it")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def unit_text(
    *,
    working_dir: str,
    env_file: str,
    bind: str,
    port: int,
    commit_file: str,
) -> str:
    """The service that keeps the console up."""
    return f"""[Unit]
Description=OSINT console
Documentation=https://example.invalid/osint
# The bind address does not exist until the tailnet is up, and a unit that
# starts before it fails at boot while working perfectly when tried by hand.
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={working_dir}
# Beside the unit rather than in it: unit files are world-readable.
EnvironmentFile={env_file}
# Which build is being served, in the journal, so a fix that was pulled and
# not rebuilt is a line to read rather than a mystery.
ExecStartPre=/bin/sh -c 'echo "console build: $(cat {commit_file} 2>/dev/null || echo unknown)"'
ExecStart=/usr/bin/env pnpm exec next start -H {bind} -p {port}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
```

- [ ] **Step 4: Run the tests**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_console_unit.py -v`
Expected: PASS.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

- [ ] **Step 6: Commit**

```bash
git add app/devx/console_unit.py tests/test_console_unit.py
git commit -m "feat(devx): the console's service, rendered where its addresses are known"
```

---

### Task 3: Build it, install it, start it

**Files:**
- Create: `scripts/serve-up.sh`
- Modify: `Makefile` (beside `share:`, around line 55)
- Test: `tests/test_lan_share.py` (the structural tests at the end of that file)

**Interfaces:**
- Consumes: `python -m app.devx.lan_share serve` from Task 1; `app.devx.console_unit` from Task 2.
- Produces: `make serve-build`, `make serve-install`, `make serve`.

- [ ] **Step 1: Write the failing tests**

`tests/test_lan_share.py` already ends with structural tests that read `Makefile`, `docker-compose.yml` and `scripts/dev-up.sh` as text — `test_make_share_exists_and_does_not_persist_the_choice` is the model. Append, in that style:

```python
def _serve_script() -> str:
    return (Path(__file__).resolve().parents[1] / "scripts/serve-up.sh").read_text()


def test_the_serve_targets_exist() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    for target in ("serve-build:", "serve-install:", "serve:"):
        assert target in makefile


#: systemd is Linux's. On anything else the install would write a file nothing
#: reads and report success, which is worse than refusing.
def test_installing_the_unit_refuses_where_there_is_no_systemd() -> None:
    script = _serve_script()
    assert "uname" in script
    assert "systemctl" in script


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
#: /etc without being shown is a file nobody reviewed.
def test_the_install_shows_the_unit_before_writing_it() -> None:
    script = _serve_script()
    assert "sudo" in script
    assert "cat" in script or "printf" in script
```

- [ ] **Step 2: Run them and watch them fail**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_lan_share.py -k "serve" -v`
Expected: FAIL — `FileNotFoundError` for `scripts/serve-up.sh`.

- [ ] **Step 3: Write the script**

Create `scripts/serve-up.sh`. This is the whole file:

```bash
#!/usr/bin/env bash
#: Build the console, install its service, and start the stack for the tailnet.
#:
#: Separate from `dev-up.sh` on purpose. That script supervises `next dev` by
#: hand — pid files, a mode signature, a sweep for the child `next-server`, a
#: restart when the bind changed — and every one of those is systemd's job
#: here. A script that did both would be arguing with the service manager
#: about who owns the process.
set -euo pipefail
cd "$(dirname "$0")/.."

UNIT=osint-console.service
UNIT_PATH=/etc/systemd/system/$UNIT
ENV_PATH=/etc/osint-console.env
COMMIT_FILE="$PWD/osint-frontend/.next/BUILD_COMMIT"

#: `app/devx/` imports nothing but the standard library so a machine that has
#: not built a virtualenv can still derive its own settings — the same reason
#: `dev-up.sh` and `env_setup.py` choose an interpreter this way.
serve_python() {
  if [ -x .venv/bin/python ]; then
    echo .venv/bin/python
    return 0
  fi
  command -v python3 2>/dev/null || true
}

#: Every setting serve mode derives, into this shell. The module prints
#: nothing on failure and says why on stderr, so a refusal cannot be evalled
#: into a half-configured start.
apply_serve_mode() {
  local python
  python="$(serve_python)"
  if [ -z "$python" ]; then
    echo "serve mode needs python3, and there is none on PATH." >&2
    exit 1
  fi
  local exports
  if ! exports="$("$python" -m app.devx.lan_share serve)"; then
    exit 1
  fi
  eval "$exports"
}

render_unit() {
  local python
  python="$(serve_python)"
  "$python" - "$@" <<'PY'
import sys

from app.devx.console_unit import unit_text

working_dir, env_file, bind, port, commit_file = sys.argv[1:6]
sys.stdout.write(
    unit_text(
        working_dir=working_dir,
        env_file=env_file,
        bind=bind,
        port=int(port),
        commit_file=commit_file,
    )
)
PY
}

render_env_file() {
  local python
  python="$(serve_python)"
  "$python" - <<'PY'
import os
import sys

from app.devx.console_unit import env_file_text

#: Only what the console needs to run. The whole environment would carry
#: every secret this shell has ever seen into a file on disk.
keys = [k for k in os.environ if k.startswith("NEXT_PUBLIC_")]
keys += ["OSINT_SERVE_HOST", "OSINT_SERVE_URL"]
env = {k: os.environ[k] for k in keys if os.environ.get(k)}
env["NODE_ENV"] = "production"
sys.stdout.write(env_file_text(env))
PY
}

cmd_build() {
  apply_serve_mode
  echo "→ building the console for the tailnet"
  echo "  console: $OSINT_SERVE_URL"
  echo "  API:     $NEXT_PUBLIC_API_URL"
  echo "  (both are compiled into the bundle — a new tailnet name means building again)"
  if [ ! -d osint-frontend/node_modules ]; then
    echo "  installing console packages (first run — several minutes)"
    (cd osint-frontend && pnpm install --frozen-lockfile)
  fi
  (cd osint-frontend && pnpm build)
  git rev-parse --short HEAD >"$COMMIT_FILE"
  echo "  built $(cat "$COMMIT_FILE")"
}

cmd_install() {
  #: systemd is Linux's. Writing a unit anywhere else produces a file nothing
  #: reads, and reporting success for it is worse than refusing.
  if [ "$(uname -s)" != "Linux" ]; then
    echo "The console's service is systemd, which is Linux. This machine is $(uname -s)." >&2
    echo "Run this on the board itself." >&2
    exit 1
  fi
  apply_serve_mode

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  render_env_file >"$tmp/console.env"
  render_unit \
    "$PWD/osint-frontend" "$ENV_PATH" "$FRONTEND_BIND" "${FRONTEND_PORT:-3000}" "$COMMIT_FILE" \
    >"$tmp/$UNIT"

  echo "→ this is the service that would be installed at $UNIT_PATH:"
  echo
  cat "$tmp/$UNIT"
  echo
  echo "  and $ENV_PATH, readable by root only, carrying the console's settings."
  read -r -p "Install and enable it? [y/N] " answer
  case "$answer" in
    y | Y) ;;
    *)
      echo "  nothing written"
      exit 0
      ;;
  esac

  #: 0600 because it carries NEXT_PUBLIC_API_TOKEN. The unit beside it is
  #: 0644 and holds no secret, which is the whole reason the two are separate.
  sudo install -m 0600 "$tmp/console.env" "$ENV_PATH"
  sudo install -m 0644 "$tmp/$UNIT" "$UNIT_PATH"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$UNIT"
  sudo systemctl status "$UNIT" --no-pager || true
  echo "  open $OSINT_SERVE_URL"
}

cmd_start() {
  apply_serve_mode
  if [ ! -f "$COMMIT_FILE" ]; then
    echo "No console build yet. Run \`make serve-build\` first." >&2
    exit 1
  fi
  echo "→ stores and backend, published on $API_BIND"
  COMPOSE_PROFILES=app docker compose up -d
  if [ -f "$UNIT_PATH" ]; then
    sudo systemctl restart "$UNIT"
    echo "→ console restarted (build $(cat "$COMMIT_FILE"))"
  else
    echo "→ the console's service is not installed — run \`make serve-install\`" >&2
  fi
  echo "  open $OSINT_SERVE_URL"
}

case "${1:-}" in
  build) cmd_build ;;
  install) cmd_install ;;
  start) cmd_start ;;
  *)
    echo "usage: serve-up.sh [build|install|start]" >&2
    exit 2
    ;;
esac
```

Two things to check while writing it, because both are easy to get wrong and
neither shows up until the board is running:

- `render_env_file` passes only `NEXT_PUBLIC_*` plus the two `OSINT_SERVE_*`
  keys. Passing the whole environment would write every secret this shell has
  seen into a file on disk.
- The heredocs that carry Python are quoted (`<<'PY'`), so the shell does not
  expand `$` inside them. Unquoting one would substitute shell variables into
  Python source.

- [ ] **Step 4: Add the make targets**

Beside `share:` in the `Makefile`, matching the existing `##` help style:

```make
serve-build:  ## Build the console for the tailnet — run this after every pull
	@bash scripts/serve-up.sh build

serve-install:  ## Install and enable the console's service (asks for sudo, Linux only)
	@bash scripts/serve-up.sh install

serve:  ## Start the stack for the tailnet and restart the served console
	@bash scripts/serve-up.sh start
```

- [ ] **Step 5: Run the tests**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest tests/test_lan_share.py -v`
Expected: PASS, including the existing structural tests — they read the same files this task edited.

- [ ] **Step 6: Check the script parses and the help reads right**

Run: `bash -n scripts/serve-up.sh && make help | grep serve`
Expected: no syntax error, and three lines whose descriptions say what each does.

Do NOT run `make serve-install` here. It writes to `/etc` and enables a service; it is the operator's to run on the board, and this is not the board.

- [ ] **Step 7: Commit**

```bash
git add scripts/serve-up.sh Makefile tests/test_lan_share.py
git commit -m "feat(devx): build the console for the tailnet, and keep it up"
```

---

### Task 4: Say how to run it

**Files:**
- Modify: `README.md` — a new `<details>` block after the existing quick-start blocks

**Interfaces:**
- Consumes: everything above. No code.

- [ ] **Step 1: Read the quick-start section first**

Run: `sed -n '40,200p' README.md`

Every block there is self-contained: from nothing to a running console, in order, nothing to look up elsewhere. The new block is a fourth of the same kind and must read like the others — plain, second person, explaining the reason rather than listing the setting.

- [ ] **Step 2: Write the block**

Titled for what it does, not for the technology: **Run it as a server**. In order:

1. What this is. The stack already survives a reboot on the backend side, because the containers restart themselves. The console does not — `make up` runs a development server that dies with the power. This makes the console a service, and the board reachable from a phone.
2. Tailscale, as a prerequisite rather than something this repository installs: install it on the board and on the phone or laptop, `sudo tailscale up`, and the command that shows the name the board answers to — `tailscale status`.
3. `API_AUTH_TOKEN` must be set in `.env`. Say why in one sentence: it is the only thing between a device on the tailnet and an endpoint that spends model inference per call, and serve mode refuses to start without it.
4. `make serve-build` — minutes, and what it bakes in. Say the sharp part outright: the tailnet name is compiled into the console's bundle, so changing that name means building again, not restarting.
5. `make serve-install` — what it will ask for (sudo), what it writes (`/etc/systemd/system/osint-console.service` and `/etc/osint-console.env`, the second readable only by root because it carries the token), and that it prints the unit before writing it.
6. `make serve` — starts the containers on the tailnet address and restarts the console.
7. Reboot the board and open the URL from the phone. That is the test, and it is the only one that proves it.
8. Where to look when it does not work: `systemctl status osint-console`, `journalctl -u osint-console -n 50`, and the line the unit logs at every start saying which build it is serving.
9. One short passage on what this is not: the console has no login, and the bundle it serves carries the API token to whoever downloads it. The tailnet is the boundary. Do not port-forward it. A public URL needs an identity layer in front, which is separate work.

- [ ] **Step 3: Read it back whole**

Run: `sed -n '/Run it as a server/,/<\/details>/p' README.md`

Check: the commands run start to finish with no gap, nothing refers to a step that is not there, and a reader who has only ever run `make up` can follow it.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): from a desk console to a board you can reach"
```

---

### Task 5: Verify, squash, and open the pull request

- [ ] **Step 1: Backend gates**

Run: `API_AUTH_TOKEN="" .venv/bin/pytest -q --ignore=tests/test_presence_aircraft.py --ignore=tests/test_presence_watchlist.py`
Then: `.venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests`

The two ignored files fail in this working copy for a reason that predates the branch — an untracked `data/watchlist.json` reached through a fallback path. Say so in the PR rather than quietly excluding them.

- [ ] **Step 2: Frontend gates**

Nothing in this branch changes frontend source. Run them anyway, once, because the build path is what the whole branch is about:

Run: `cd osint-frontend && pnpm exec tsc --noEmit && pnpm vitest run`

- [ ] **Step 3: Squash to one commit**

One issue, one branch, one pull request, one commit.

```bash
git reset --soft $(git merge-base main HEAD) && git status
```

Read the staged list before committing: it should hold exactly the files this plan names, plus the spec and this plan document.

```bash
git commit -m "feat(devx): the board boots into a console reachable from a phone"
```

- [ ] **Step 4: Open the issue and the pull request**

The maintainer merges. An agent never does. The PR body says what the three targets do, that the backend needed nothing because compose already restarts, and — plainly — that the console has no login and the tailnet is the boundary.

- [ ] **Step 5: Say what was not verified**

Report to the operator: no board was booted. Everything here is tested as text and as derivation — the unit's contents, the mode's settings, the script's shape. That systemd starts it at boot, that the phone loads it, and that `next start` binds the tailnet address are confirmed by rebooting the board once, and nothing in this branch stands in for that.
