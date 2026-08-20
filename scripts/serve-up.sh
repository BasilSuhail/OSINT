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
STACK_UNIT=osint-stack.service
STACK_UNIT_PATH=/etc/systemd/system/$STACK_UNIT
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

env_value() { # key — the value in .env, if .env sets one
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

#: Every NEXT_PUBLIC_* key `.env` sets, exported for whichever command runs
#: next to compile it in or write it to the service's env file. `.env` never
#: reaches a Python subprocess's environment on its own — `app/devx/` is
#: standard-library only, on purpose — so this is the only route a value
#: typed there takes into the bundle or the unit. Same fix, same reasoning,
#: as `dev-up.sh`'s `load_frontend_public_env`: every key it finds, not a
#: hand-kept list of them, and an already-exported value wins over `.env`'s.
load_frontend_public_env() {
  [ -f .env ] || return 0

  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "" | \#*) continue ;;
    esac

    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      NEXT_PUBLIC_*)
        if [ -z "${!key+x}" ]; then
          case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
          esac
          export "$key=$value"
        fi
        ;;
    esac
  done < .env
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

  #: `lan_share serve` reads these five straight from this process's
  #: environment — it parses no file itself. `dev-up.sh`'s
  #: `apply_network_mode` solves the identical problem the identical way:
  #: pull the named keys `.env` sets, into this shell, before the subprocess
  #: that needs them runs. Without this, `API_AUTH_TOKEN` is never set, and
  #: serve mode refuses every time rather than only when a token is genuinely
  #: missing.
  export API_AUTH_TOKEN="${API_AUTH_TOKEN:-$(env_value API_AUTH_TOKEN)}"
  export API_CORS_ORIGINS="${API_CORS_ORIGINS:-$(env_value API_CORS_ORIGINS)}"
  export API_PORT="${API_PORT:-$(env_value API_PORT)}"
  export FRONTEND_PORT="${FRONTEND_PORT:-$(env_value FRONTEND_PORT)}"
  export OSINT_PUBLIC_HOST="${OSINT_PUBLIC_HOST:-$(env_value OSINT_PUBLIC_HOST)}"

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

#: The unit that starts the containers at boot, once the tailnet address is
#: actually on an interface. See `stack_unit_text` for why ordering docker
#: after tailscaled is not the same question.
render_stack_unit() {
  local python
  python="$(serve_python)"
  "$python" - "$@" <<'PY'
import os
import sys

from app.devx.console_unit import stack_unit_text

working_dir, bind = sys.argv[1:3]

#: What compose cannot get from `.env`. `API_BIND` and the origin list are
#: *derived* by serve mode and exist only in the shell that derived them, and
#: compose substitutes from the process environment in preference to `.env` —
#: so this is the only route they take into a start that systemd runs rather
#: than the operator. Everything else compose reads from `.env` itself,
#: `API_AUTH_TOKEN` above all: a secret has no business in a unit file, which
#: is world-readable.
env = {"COMPOSE_PROFILES": "app", "API_BIND": bind}
for key in ("API_CORS_ORIGINS", "API_PORT"):
    if os.environ.get(key):
        env[key] = os.environ[key]

sys.stdout.write(stack_unit_text(working_dir=working_dir, bind=bind, environment=env))
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
  #: The bundle compiles in NEXT_PUBLIC_* from this shell's environment.
  #: Serve mode has just derived NEXT_PUBLIC_API_URL; everything else
  #: NEXT_PUBLIC_* — above all NEXT_PUBLIC_API_TOKEN, which is how the
  #: console authenticates every request once it is running — lives only in
  #: `.env`, and reaches the build from here or not at all.
  load_frontend_public_env
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
  #: The installed service reads the env file rendered below, not this
  #: shell — so `.env`'s NEXT_PUBLIC_* keys have to be loaded before that
  #: file is rendered, or the service starts as unable to authenticate as
  #: the build was.
  load_frontend_public_env

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  render_env_file >"$tmp/console.env"
  render_unit \
    "$PWD/osint-frontend" "$ENV_PATH" "$FRONTEND_BIND" "${FRONTEND_PORT:-3000}" "$COMMIT_FILE" \
    >"$tmp/$UNIT"
  render_stack_unit "$PWD" "$API_BIND" >"$tmp/$STACK_UNIT"

  echo "→ these are the two services that would be installed:"
  echo
  echo "--- $STACK_UNIT_PATH"
  cat "$tmp/$STACK_UNIT"
  echo "--- $UNIT_PATH"
  cat "$tmp/$UNIT"
  echo
  echo "  and $ENV_PATH, readable by root only, carrying the console's settings."
  read -r -p "Install and enable them? [y/N] " answer
  case "$answer" in
    y | Y) ;;
    *)
      echo "  nothing written"
      exit 0
      ;;
  esac

  #: 0600 because it carries NEXT_PUBLIC_API_TOKEN. The units beside it are
  #: 0644 and hold no secret, which is the whole reason they are separate
  #: files.
  sudo install -m 0600 "$tmp/console.env" "$ENV_PATH"
  sudo install -m 0644 "$tmp/$STACK_UNIT" "$STACK_UNIT_PATH"
  sudo install -m 0644 "$tmp/$UNIT" "$UNIT_PATH"
  sudo systemctl daemon-reload
  #: The stack first, and `--now` on it, so the containers are reconciled onto
  #: the tailnet bind before the console starts answering for them.
  sudo systemctl enable --now "$STACK_UNIT"
  sudo systemctl enable --now "$UNIT"
  sudo systemctl status "$STACK_UNIT" "$UNIT" --no-pager || true
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
