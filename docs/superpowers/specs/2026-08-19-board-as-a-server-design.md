# The board as a server

## The problem

The stack starts when somebody types `make up`. The backend survives a reboot
already — compose carries `restart: unless-stopped` and Docker starts at boot,
so postgres, redis, the API, the workers and beat all come back on their own.
The console does not. `scripts/dev-up.sh` spawns `pnpm dev` under `nohup`, which
dies with the power and never returns, and which is a development server:
it recompiles on request and holds memory a small board does not have.

And nothing is reachable from anywhere but the desk. `make share` opens the LAN
and says plainly that it adds no credential.

So: a board that boots into a working console, reachable from a phone anywhere,
without typing anything and without opening a port to the internet.

## The three modes

`app/devx/lan_share.py` already derives four settings from one address, for two
modes. This adds a third.

| | `locked` (`make up`) | `share` (`make share`) | `serve` (`make serve`) |
|---|---|---|---|
| Reachable by | this machine | the local network | devices on the tailnet |
| Console runs | `next dev` | `next dev` | `next start`, behind Tailscale Serve HTTPS |
| Survives reboot | no | no | yes |
| Credential | none needed | none — and it says so | `API_AUTH_TOKEN`, required |

`locked` and `share` keep their exact behaviour. The development loop does not
change.

## What serve derives

`serve_env()` returns the same shape its neighbours return:

- `API_BIND` — loopback. The private HTTPS edge reaches Next, and Next reaches
  the API locally. No application process needs a tailnet bind.
- `API_CORS_ORIGINS` — the tailnet hostname's origin, added to whatever `.env`
  already configures rather than replacing it, as share mode does.
- `FRONTEND_BIND` — loopback. Tailscale Serve officially proxies local HTTP
  targets and terminates the private HTTPS origin the installed app requires.
- `NEXT_PUBLIC_API_URL` — `/api`, keeping every browser request on the secure
  frontend origin.
- `API_PROXY_TARGET` — the API's loopback address, used by Next behind that
  same-origin route.
- `OSINT_SERVE_URL` — the tailnet's HTTPS MagicDNS name, with no raw port.

The fourth setting share needs drops out. `LAN_SHARE_HOST` exists only because
`next dev` refuses to serve its own `/_next/*` resources to a host that is not
localhost; `next start` has no such rule, and a setting that does nothing is
better absent than present and inert.

The hostname comes from `tailscale status --json`. `OSINT_PUBLIC_HOST` remains a
share-mode override, but cannot replace this name: Tailscale provisions the
private HTTPS certificate for the node's MagicDNS name.

## Why serve is remembered when share is not

`lan_share.py` argues, at length and correctly, that share mode must never be
written to a file: "the failure this exists to prevent is not *cannot share*, it
is *still sharing somewhere else*", and a stack opened at home and restarted
elsewhere must come back closed.

Serve inverts that. A server that forgets it is a server is the failure. The
reason the argument does not carry across is that the two modes are protected by
different things. Share's protection is the bind address — take the address away
and the protection is gone, which is why it must not persist. Serve's protection
is the tailnet: a device that is not on it cannot resolve or route to the board
at all, whatever the board is bound to. Persisting the mode does not widen the
audience.

That reasoning belongs in the module beside the paragraph it contradicts. A
future reader who finds only the older argument will read the newer mode as a
mistake.

## The build, and what it bakes in

`make serve-build` runs `pnpm build` with the serve-mode environment in place.

This is the sharp edge of the whole design. In development, frontend settings
are read when the process spawns, so `dev-up.sh` can restart the console to
change one. A production build compiles both the public settings and the rewrite
table. The consequence, which the build target prints rather than leaving to be
discovered: **change the API port and the console must be rebuilt, not
restarted.**

The target prints the HTTPS console URL, browser API path and proxy target, then
writes the commit it built from where the unit can read it.

Building on the board rather than elsewhere: it is minutes and it is memory
hungry, but it happens when the operator pulls new code, not on a schedule and
not at boot. The alternative — building at every start — costs those minutes
after every power cut and turns a failed build into no console at all.

## Boot

Two units divide the two failure modes:

- `osint-stack.service` reconciles the containers, then checks `/health`
  through the loopback port Docker reports as published. This catches the
  missing endpoint that an in-container health check cannot see without
  persisting mutable `.env` values in the unit.
- `osint-console.service` starts the built console on loopback after the stack:
  - `ExecStart` runs `next start` bound as serve mode derived, from
    `osint-frontend`.
  - `Restart=always`, so a crash comes back.
  - `After=network-online.target tailscaled.service`: the private HTTPS ingress
    returns with the tailnet, while the process's loopback bind remains local.
  - `ExecStartPost` checks `/api/health` through Next, proving the compiled
    rewrite and API together.
  - `EnvironmentFile` points at a generated file, so no secret is written into
    the unit.
  - The commit being served is logged at start, so a stale build is a line in
    `journalctl` rather than a mystery about why a fix is not showing.

`make serve-install` renders both units, prints them in full, asks before
writing, enables them, then persists a Tailscale Serve HTTPS route to the
loopback console. Tailscale resumes that route after reboot without exposing it
outside the tailnet.

## Refusals

Serve mode refuses to start, naming the fix, when:

- **Tailscale is not up.** There is no private hostname for the HTTPS ingress.
- **HTTPS Certificates are disabled.** MagicDNS is a separate setting. Install
  proves certificate eligibility in a temporary directory before it writes or
  enables either service, so failure cannot strand a loopback-only console.
- **`API_AUTH_TOKEN` is empty.** On a laptop an empty token is a convenience. On
  a machine that is up all the time and reachable from a phone, it is the only
  thing between a tailnet device and `POST /brain/ask`, which spends local model
  inference per call. Empty is refused rather than warned about.

Both refusals are the mode's own, not the unit's, so they happen at
`make serve`, `make serve-build`, and `make serve-install` where a person is
watching.

## Testing

`lan_share.py` has real tests, and `serve_env()` gets the same:

- derivation — the three settings, from a known hostname
- hostname detection from a captured `tailscale status --json` payload
- `OSINT_PUBLIC_HOST` overriding detection
- no tailnet — raises, with a message naming the fix
- empty `API_AUTH_TOKEN` — raises, with a message naming the fix
- `locked` and `share` unchanged: their existing tests must pass untouched

The unit files are produced by functions that return text, tested on what they
render: loopback binds, host-level and proxy-level health checks, restart
policies, and no secret inline. systemd itself is not tested — the daemon is
not this project's to verify.

The board booting into a working console is confirmed by the operator, once, by
rebooting it. There is no test that can stand in for that.

## Out of scope

The public URL and its login. The choice made alongside this design is
Cloudflare Access fronting a tunnel — identity checked before a request reaches
the board, no auth code in this repository. That is its own spec, and this
design leaves the seam for it: Access fronts a tunnel pointing at the same
`next start` this unit already runs, so nothing built here is rebuilt when it
lands.

Until it does, the board is reachable on the tailnet and nowhere else. It must
not be port-forwarded: the console has no login, and the bundle it serves
carries the API token to whoever downloads it.
