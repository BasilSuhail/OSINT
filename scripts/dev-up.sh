#!/usr/bin/env bash
# Start the whole local app with one command.
#
# Stores (Postgres + Redis) run in Docker. The three backend processes
# (Celery worker, Celery beat, FastAPI read-API) are started in the BACKGROUND
# with their logs under logs/ and PIDs under logs/*.pid. The dashboard is also
# started in the background so one command brings the full app up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

# Settings first (#957). A key missing from .env is a feature silently off and
# a typed key name loads as nothing, so both are worth a sentence before
# anything starts. Never fatal: a warning about a key nobody uses must not stop
# a console from running, and this script has to work on a box where python3 is
# missing entirely.
if command -v python3 >/dev/null 2>&1 && [ -f scripts/env_setup.py ]; then
  if [ ! -f .env ]; then
    echo "  no .env yet — creating one from env.example"
    python3 scripts/env_setup.py sync || true
  else
    python3 scripts/env_setup.py check || \
      echo "  (run \`make env\` to add missing keys; starting anyway)"
  fi
fi

#: The data directory, made here rather than left to compose. A bind mount whose
#: source does not exist is created by the Docker daemon, which runs as root — so
#: on a fresh clone `data/` arrived owned by root while the containers run as the
#: operator (DOCKER_UID, #984). Beat could not write its schedule and crash-looped
#: on `[Errno 13] Permission denied: '/data/celerybeat-schedule'`; the story
#: export failed the same way on `/data/exports`.
#:
#: After the settings, because the location is one of them. Made by the person
#: running the command, so it belongs to them.
#:
#: An existing directory is left exactly as it is. `data/postgres` belongs to the
#: database image's own user, and chowning it is how you stop Postgres starting.
ensure_data_dir() {
  local configured
  configured="$(sed -n 's/^OSINT_DATA_DIR=//p' .env 2>/dev/null | tail -n1)"
  configured="${configured%\"}"
  configured="${configured#\"}"
  mkdir -p "${configured:-./data}" 2>/dev/null ||
    echo "  could not create ${configured:-./data} — check you can write there" >&2
}
ensure_data_dir

DOCKER_WAIT_SECONDS="${DOCKER_WAIT_SECONDS:-30}"
DOCKER_WAIT_STEP="${DOCKER_WAIT_STEP:-2}"
API_WAIT_SECONDS="${API_WAIT_SECONDS:-20}"
FRONTEND_WAIT_SECONDS="${FRONTEND_WAIT_SECONDS:-60}"
DOCKER_WAIT_MESSAGE_EVERY="${DOCKER_WAIT_MESSAGE_EVERY:-10}"
OLLAMA_WAIT_SECONDS="${OLLAMA_WAIT_SECONDS:-30}"
# The models are read where they are pulled, in ensure_ollama, and their
# defaults track app/settings.py: brain_model, qa_model, embed_model. Setting
# BRAIN_MODEL, QA_MODEL or EMBED_MODEL in `.env` overrides one of them for both
# the pull and the application.

load_frontend_public_env() {
  [ -f .env ] || return 0

  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ""|\#*) continue ;;
    esac

    key="${line%%=*}"
    value="${line#*=}"
    #: Every NEXT_PUBLIC_* key, not a hand-kept list of them. `.env` is at the
    #: repository root and the dashboard runs from osint-frontend/, so Next
    #: never reads that file and this is the only route anything in it takes to
    #: the browser bundle. The list this replaces was a partial copy of
    #: env.example and had fallen behind by exactly one key —
    #: NEXT_PUBLIC_API_TOKEN, the one every request depends on. The console
    #: loaded, sent no credential, and every panel came back 401, which reads on
    #: screen as "no events" rather than as a fault (#976).
    #:
    #: The prefix is the contract. Next already treats it as "safe to compile
    #: into the bundle", so a key carrying it is one somebody has already
    #: decided the browser may see. A second list here decides nothing and can
    #: only fall behind again.
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

docker_ready() {
  if [ -n "${DOCKER_HOST:-}" ]; then
    if docker info >/dev/null 2>&1; then
      return 0
    fi

    local configured_host
    configured_host="$DOCKER_HOST"
    if DOCKER_HOST= docker info >/dev/null 2>&1; then
      echo "  DOCKER_HOST=${configured_host} is unreachable; falling back to local socket."
      export DOCKER_HOST=
      return 0
    fi
    return 1
  fi

  docker info >/dev/null 2>&1
}

docker_process_running() {
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -x "Docker" >/dev/null 2>&1 && return 0
    pgrep -x "com.docker.backend" >/dev/null 2>&1 && return 0
    pgrep -f "com\\.docker" >/dev/null 2>&1 && return 0
    pgrep -f "Docker Desktop" >/dev/null 2>&1 && return 0
  fi
  return 1
}

ensure_docker() {
  if docker_ready; then
    return
  fi

  if [ "${DOCKER_AUTOSTART:-1}" = "1" ] && command -v open >/dev/null 2>&1; then
    if docker_process_running; then
      echo "→ Docker app detected, waiting for engine socket"
    else
      echo "→ Docker is not running; opening Docker Desktop"
      open -a Docker >/dev/null 2>&1 || true
      echo "  waiting up to ${DOCKER_WAIT_SECONDS}s for Docker to become available"
    fi
  else
    if docker_process_running; then
      echo "→ Docker app detected, waiting for engine socket"
      echo "  waiting up to ${DOCKER_WAIT_SECONDS}s for Docker to become available"
    else
      echo "Docker is not reachable. Start Docker Desktop, then run make start again." >&2
      exit 1
    fi
  fi

  printf "→ waiting for Docker"
  max_tries=$(( (DOCKER_WAIT_SECONDS + DOCKER_WAIT_STEP - 1) / DOCKER_WAIT_STEP ))
  message_interval=$((DOCKER_WAIT_MESSAGE_EVERY / DOCKER_WAIT_STEP))
  [ "$message_interval" -lt 1 ] && message_interval=1
  for i in $(seq 1 "$max_tries"); do
    if docker_ready; then
      printf " ✓ ready\n"
      return
    fi
    printf "."
    if [ $((i % message_interval)) -eq 0 ]; then
      if docker_process_running; then
        echo
        echo "  Docker process is running; waiting for API socket."
      else
        echo
        echo "  Docker process not detected yet; if app is not running, start Docker Desktop."
      fi
      if [ -n "${DOCKER_HOST:-}" ]; then
        echo "  DOCKER_HOST is set to ${DOCKER_HOST}"
      fi
      printf "→ waiting for Docker"
    fi
    sleep "$DOCKER_WAIT_STEP"
  done
  printf "\nDocker did not become ready in ${DOCKER_WAIT_SECONDS}s.\n" >&2
  if docker_process_running; then
    echo "Docker Desktop is running, but daemon/socket is not available yet." >&2
    echo "Restart Docker Desktop, then run make up again." >&2
  else
    echo "Start/activate Docker Desktop, then run make up again." >&2
  fi
  exit 1
}

ollama_ready() {
  curl -s -m2 http://localhost:11434/api/tags >/dev/null 2>&1
}

ensure_ollama() {
  # The brain (situation narrative, Q&A, story enrichment, nightly validator)
  # reaches Ollama on localhost:11434. Bring it up here so one `make up` starts
  # the whole app WITH its brain. Strictly best-effort: if Ollama is absent,
  # slow, or the pull fails, the app still runs and the brain degrades cleanly
  # (narrate/enrich skip, /brain/ask answers "offline"). Never aborts make up.
  if [ "${OLLAMA_AUTOSTART:-1}" != "1" ]; then
    echo "  ollama autostart disabled (OLLAMA_AUTOSTART=0)"
    return 0
  fi
  if ! command -v ollama >/dev/null 2>&1; then
    echo "  ollama not installed; skipping (brain features stay dormant)"
    return 0
  fi

  if ollama_ready; then
    echo "  ollama already running"
  else
    echo "  starting ollama"
    nohup ollama serve >logs/ollama.log 2>&1 &
    echo $! >logs/ollama.pid
    printf "  waiting for ollama"
    for _ in $(seq 1 "$OLLAMA_WAIT_SECONDS"); do
      if ollama_ready; then break; fi
      printf "."
      sleep 1
    done
    if ollama_ready; then
      printf " \342\234\223 ready\n"
    else
      printf "\n  ollama did not become ready in %ss; brain stays dormant (see logs/ollama.log).\n" "$OLLAMA_WAIT_SECONDS"
      return 0
    fi
  fi

  # Every model the settings name, not only the first one (#986). Three
  # settings name three models — the situation narrative, the Ask panel and the
  # embeddings — and pulling one of them produced a console where the narrative
  # worked and every question came back "The brain is offline right now.",
  # because the Ask request asked for a model that was never downloaded and the
  # API turned the 404 into that sentence. Every check the message invites you
  # to make passes, since the service really is running and reachable.
  #
  # Defaults track app/settings.py. A model named in `.env` is pulled instead,
  # which is how somebody points the Ask panel at a smaller one.
  local model
  for model in \
    "${BRAIN_MODEL:-llama3.2:3b}" \
    "${QA_MODEL:-qwen3.5:4b-q4_K_M}" \
    "${EMBED_MODEL:-nomic-embed-text}"; do
    ensure_ollama_model "$model"
  done
}

ensure_ollama_model() {
  local wanted="$1"
  # Right after `ollama serve` boots, the model listing is briefly flaky — the
  # CLI and the /api/tags endpoint can each momentarily miss a model that IS on
  # disk. Check BOTH and retry for a few seconds so we never trigger a spurious
  # pull for an already-present model. On a genuinely fresh box every check
  # misses and we pull once (the few seconds of waiting are negligible next to
  # the download).
  local have_model=""
  for _ in $(seq 1 8); do
    if ollama list 2>/dev/null | grep -q "$wanted" ||
      curl -s -m2 http://localhost:11434/api/tags 2>/dev/null | grep -q "$wanted"; then
      have_model=1
      break
    fi
    sleep 1
  done
  if [ -z "$have_model" ]; then
    echo "  pulling model $wanted (one-time download)…"
    if ! ollama pull "$wanted" >>logs/ollama-pull.log 2>&1; then
      echo "  pull of $wanted failed (see logs/ollama-pull.log); the features using it stay dormant."
    fi
  fi
}

FRONTEND_PORT_DEFAULT=3000

#: What the running dashboard was started with. Without it a mode change would
#: find a live process, report it as satisfying the request, and keep serving
#: the previous mode (#928).
#:
#: The bind address is not enough on its own. `NEXT_PUBLIC_API_URL` is compiled
#: in at start, so a share on one network and a share on the next — same bind,
#: different address — would reuse a dashboard pointing at an address that no
#: longer exists, and fail as an empty console rather than as an error.
FRONTEND_MODE_FILE="logs/frontend.mode"

frontend_mode_signature() {
  printf '%s %s' "$FRONTEND_BIND" "${NEXT_PUBLIC_API_URL:-}"
}

env_value() { # key — the value in .env, if .env sets one
  [ -f .env ] || return 0
  sed -n "s/^$1=//p" .env | tail -n1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

#: The interpreter that derives the network mode. `app/devx/lan_share.py`
#: imports nothing but the standard library, so the project's virtual
#: environment is not needed to run it and requiring one refused to share on
#: every machine that had not built one yet — pointing at a `make install`
#: target that does not exist (#970). The venv is still preferred when it is
#: there, so a machine that has one keeps using the interpreter it was built
#: with. `scripts/env_setup.py` already runs this way, for the same reason.
share_python() {
  if [ -x .venv/bin/python ]; then
    echo .venv/bin/python
    return 0
  fi
  command -v python3 2>/dev/null || true
}

apply_network_mode() {
  # Closed unless sharing was asked for (#928). The derivation — bind address,
  # CORS origins, and the API URL compiled into the browser bundle, which must
  # name an address the *guest* can resolve — lives in app/devx/lan_share.py
  # with its tests. This function only chooses a mode and evals the result.
  local mode="locked"
  if [ "${LAN_SHARE:-0}" = "1" ]; then
    mode="share"
  fi

  local python
  python="$(share_python)"
  if [ -z "$python" ]; then
    if [ "$mode" = "share" ]; then
      echo "Sharing needs python3, and there is none on PATH." >&2
      exit 1
    fi
    # Locked is two constants, so a missing interpreter must never stop the
    # safe path.
    export API_BIND=127.0.0.1 FRONTEND_BIND=127.0.0.1
    return
  fi

  # Whatever .env configures stays configured: share mode adds the guest's
  # origin to the list rather than replacing it.
  export API_CORS_ORIGINS="${API_CORS_ORIGINS:-$(env_value API_CORS_ORIGINS)}"
  export API_PORT="${API_PORT:-$(env_value API_PORT)}"
  export FRONTEND_PORT="${FRONTEND_PORT:-$FRONTEND_PORT_DEFAULT}"
  #: Which of this machine's names the console should be reached by, when it
  #: should not be the detected one (#974). The same setting `make env` derives
  #: NEXT_PUBLIC_API_URL from, so the two agree instead of overwriting one
  #: another.
  export OSINT_PUBLIC_HOST="${OSINT_PUBLIC_HOST:-$(env_value OSINT_PUBLIC_HOST)}"

  local exports
  if ! exports="$("$python" -m app.devx.lan_share "$mode" 2>logs/lan-share.err)"; then
    echo "  $(tail -n1 logs/lan-share.err 2>/dev/null)" >&2
    if [ "$mode" = "share" ]; then
      exit 1
    fi
    export API_BIND=127.0.0.1 FRONTEND_BIND=127.0.0.1
    return
  fi
  eval "$exports"
}

#: What a process is actually listening on, as `address:port`, or nothing.
#:
#: `ss` first, `lsof` second. This asked lsof alone, which a desktop has and a
#: server install does not — and the failure was silent in the worst way (#972).
#: With no lsof every running dashboard looked absent, so `frontend_pid` found
#: nothing to stop, every `make up` and `make share` spawned another `next dev`
#: beside the first, and the first kept the port. The console stayed on
#: whichever address it was started with, no matter how many times the mode was
#: changed, while the script reported the change it had not made.
frontend_listener_endpoint() {
  local pid="${1:-}"
  if [ -z "$pid" ]; then
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    #: The comma matters: `pid=26,` must not match a listener held by 261.
    ss -tlnp 2>/dev/null | grep -F "pid=${pid}," | awk '{print $4}' | tail -n 1
    return
  fi

  lsof -Pan -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null | tail -n 1 | sed -n 's/.*TCP \(.*\) (LISTEN).*/\1/p'
}

frontend_listener_port() {
  local endpoint
  endpoint="$(frontend_listener_endpoint "${1:-}")"
  [ -n "$endpoint" ] || return 0
  echo "${endpoint##*:}"
}

#: The address half, normalised. Both tools spell "every interface" their own
#: way, and the comparison this feeds is against a bind address written as
#: 0.0.0.0.
frontend_listener_address() {
  local endpoint address
  endpoint="$(frontend_listener_endpoint "${1:-}")"
  [ -n "$endpoint" ] || return 0
  address="${endpoint%:*}"
  case "$address" in
    "*" | "[::]" | "::" | "0.0.0.0") echo "0.0.0.0" ;;
    *) echo "$address" ;;
  esac
}

frontend_pid() {
  local pidfile="logs/frontend.pid"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && [ -n "$(frontend_listener_port "$pid")" ]; then
      echo "$pid"
      return
    fi
  fi

  local pid
  for pid in $(pgrep -af "next-server|next dev" | awk '{print $1}' | sort -u || true); do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && [ -n "$(frontend_listener_port "$pid")" ]; then
      echo "$pid"
      return
    fi
  done

}

sync_repo() {
  # Bring the checkout up to date before anything starts (#661). Three fixes
  # were merged and none of them ran, because `make up` starts whatever is on
  # disk and nothing kept that current. Refuses on uncommitted or unpushed
  # work, and never blocks the stack from starting — the decision logic and
  # its tests live in app/devx/repo_sync.py.
  [ -x .venv/bin/python ] || return 0
  .venv/bin/python -m app.devx.repo_sync || true
}

echo "→ checkout"
sync_repo

apply_network_mode
if [ "$API_BIND" = "127.0.0.1" ]; then
  echo "→ network: this machine only"
else
  echo "→ network: shared on ${LAN_SHARE_URL:-the local network}"
fi

echo "→ stores (postgres + redis)"
ensure_docker
# A Docker Desktop daemon restart can corrupt a compose project's container
# metadata (containers listed but unaddressable: "No such container: <id>",
# issues #298 and #326). The corruption is sticky — it survives daemon
# restarts and the poisoned ids cannot be removed — so retrying under the same
# project name can never succeed. Self-heal in two stages:
#   1. plain recreate (covers transient failures);
#   2. on the corruption signature ("No such container"), bump
#      COMPOSE_PROJECT_NAME in .env to a fresh timestamped name and start
#      clean. Data lives on $OSINT_DATA_DIR bind mounts, so the new project
#      reattaches to the same Postgres/Redis state; the ghost containers stay
#      behind, inert and invisible to the new project name.
# The dev overlay mounts app/ back over the image so editing a file still takes
# effect without a rebuild (#634). It is passed explicitly rather than named
# docker-compose.override.yml, which compose would auto-load and thereby apply
# to the Pi as well.
COMPOSE_DEV_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)

compose_up() {
  docker compose "${COMPOSE_DEV_FILES[@]}" up -d "$@" >/dev/null 2>logs/compose-up.err
}

# Stores plus the profile-gated backend. Separate from compose_up so the store
# bring-up and its corruption recovery above stay unchanged.
compose_up_app() {
  COMPOSE_PROFILES=app docker compose "${COMPOSE_DEV_FILES[@]}" up -d --build "$@" \
    >/dev/null 2>logs/compose-up.err
}

bump_project_name() {
  local fresh
  fresh="osint-$(date +%Y%m%d%H%M%S)"
  echo "  daemon state for this compose project is corrupted; switching project name to ${fresh}"
  if grep -q '^COMPOSE_PROJECT_NAME=' .env 2>/dev/null; then
    local tmp
    tmp="$(mktemp)"
    sed "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=${fresh}/" .env >"$tmp" && mv "$tmp" .env
  else
    printf '\nCOMPOSE_PROJECT_NAME=%s\n' "$fresh" >>.env
  fi
  export COMPOSE_PROJECT_NAME="$fresh"
}

if ! compose_up; then
  echo "  compose up failed ($(tail -n1 logs/compose-up.err 2>/dev/null)); recreating stores"
  docker compose down --remove-orphans >/dev/null 2>&1 || true
  if ! compose_up --force-recreate; then
    if grep -q "No such container" logs/compose-up.err 2>/dev/null; then
      bump_project_name
      if ! compose_up; then
        echo "Stores did not start even under a fresh project name." >&2
        echo "See logs/compose-up.err for the compose error." >&2
        exit 1
      fi
    else
      echo "Stores did not start even after a clean recreate." >&2
      echo "See logs/compose-up.err for the compose error." >&2
      exit 1
    fi
  fi
fi

spawn() { # label  cmd...
  local label="$1"; shift
  local pidfile="logs/$label.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "  $label already running (pid $(cat "$pidfile"))"
    return
  fi
  nohup "$@" >"logs/$label.log" 2>&1 &
  echo $! >"$pidfile"
  echo "  $label started (pid $!) → logs/$label.log"
}

#: Corepack asks before fetching the pinned package manager. Every command
#: below runs without a terminal attached, so there would be nobody to answer
#: it (#968). The version it fetches is the one `packageManager` names, which is
#: the point of pinning it.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

install_frontend_packages() {
  # `make up` says it starts everything, and a first run is exactly when nobody
  # has typed the install by hand. It was supplied by accident until recently —
  # some pnpm versions install before `pnpm dev` — so pinning the package
  # manager (#966) turned a hidden gap into `next: not found` (#968).
  #
  # From the lockfile, so a start never resolves a different dependency set than
  # the one that was reviewed. Skipped once the packages are there, because this
  # runs on every `make up` and the check has to cost nothing.
  if [ -d osint-frontend/node_modules ]; then
    return 0
  fi
  echo "  installing console packages (first run — several minutes)"
  if ! (cd osint-frontend && pnpm install --frozen-lockfile) >logs/frontend-install.log 2>&1; then
    echo "  install failed. Last lines of logs/frontend-install.log:" >&2
    tail -n 15 logs/frontend-install.log >&2
    return 1
  fi
  echo "  console packages installed"
}

spawn_frontend() {
  local pidfile="logs/frontend.pid"
  local pid
  # Before the signature is taken, not after: the comparison and the recorded
  # value have to be built from the same environment, or every run would see a
  # mismatch and restart a dashboard that was already correct.
  load_frontend_public_env
  pid="$(frontend_pid || true)"
  if [ -n "$pid" ]; then
    local running_mode wanted_mode bound
    running_mode="$(cat "$FRONTEND_MODE_FILE" 2>/dev/null || true)"
    wanted_mode="$(frontend_mode_signature)"
    #: The file records what was asked for, and is written the moment the
    #: process is spawned — before it has bound anything. Anything that goes
    #: wrong between those two points leaves a file claiming a mode the
    #: dashboard is not in, and the file is what the next run consults, so the
    #: wrong mode becomes permanent and every later `make share` reports a
    #: change it did not make (#972). The socket cannot lie, so ask it too.
    bound="$(frontend_listener_address "$pid")"
    if [ "$running_mode" = "$wanted_mode" ] && [ "$bound" = "$FRONTEND_BIND" ]; then
      local port
      port="$(frontend_listener_port "$pid")"
      if [ -z "$port" ]; then
        port="$FRONTEND_PORT_DEFAULT"
      fi
      echo "  frontend already running (pid $pid on $bound:$port)"
      echo "$pid" >"$pidfile"
      return
    fi

    # Up on the wrong interface. `next dev` cannot be rebound in place, and the
    # API URL in its bundle is fixed at start, so this has to be a restart.
    if [ "$running_mode" = "$wanted_mode" ]; then
      echo "  frontend restarting (recorded as ${wanted_mode}, actually bound to ${bound:-nothing})"
    else
      echo "  frontend restarting (${running_mode:-unknown} → ${wanted_mode})"
    fi
    kill "$pid" 2>/dev/null || true
    # `next dev` supervises a child server, and the sweep in frontend_pid finds
    # that child once the parent is gone. Stop both or the restart is a no-op.
    pkill -f "next-server" 2>/dev/null || true
    rm -f "$pidfile" "$FRONTEND_MODE_FILE"
  fi

  #: Before the start, not beside it: `pnpm dev` with no `node_modules` fails as
  #: `next: not found`, which names the symptom and not the cause (#968).
  if ! install_frontend_packages; then
    return 1
  fi

  nohup bash -lc "cd osint-frontend && pnpm dev -H '$FRONTEND_BIND'" >"logs/frontend.log" 2>&1 &
  echo $! >"$pidfile"
  frontend_mode_signature >"$FRONTEND_MODE_FILE"
  echo "  frontend started (pid $!) → logs/frontend.log"
}

# macOS: Celery's prefork children segfault in CoreFoundation the first time
# a forked child looks up system proxy settings (urllib → _scproxy →
# CFPreferences is not fork-safe; "Python quit unexpectedly" popups, #332).
# no_proxy="*" short-circuits the lookup (no local proxy is in use) and the
# OBJC flag covers the Objective-C side. Both are harmless on Linux.
export no_proxy="*"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

echo "→ brain (ollama)"
ensure_ollama

# The backend runs in containers (#634). It used to run as host processes here
# while `make up-docker` ran the same code in compose, and the two were not
# equivalent: the compose worker carried no `-Q`, so nothing consumed the
# `analytics` queue and thirteen heavy jobs — the composite, the CII, story
# clustering, the brain, housekeeping — were published to a queue with no
# consumer and silently never ran. One path means one thing to keep correct.
#
# Two workers either way (#384, #388): the default queue keeps a small
# concurrent pool for the I/O-bound fetchers, and every heavy job routes to
# `analytics` at concurrency 1, so peak memory is max(one job) rather than
# sum(everything beat fired together).
#
# Ollama and the frontend stay on the host. Ollama because containerising it on
# macOS loses Metal and makes the brain materially slower; the frontend because
# there is no image for it yet (#550 §3.1).
echo "→ backend (containers)"
# The backend used to run as host processes and write these (#634). A leftover
# worker.log never updates again, so `make logs` or a plain tail would show a
# frozen file exactly where a live worker used to be. Delete them rather than
# leave something that reads as a stopped service. Backend logs now come from
# `docker compose logs` — see scripts/dev-logs.sh.
for stale in worker worker-analytics beat api; do
  rm -f "logs/$stale.log" "logs/$stale.pid"
done
if ! compose_up_app; then
  # Print the error rather than the path to it (#675). The store bring-up above
  # already inlines its last line; this one sent you to a file, and the line
  # waiting in it was the whole diagnosis.
  err="$(tail -n1 logs/compose-up.err 2>/dev/null)"
  echo "Backend containers did not start: ${err:-see logs/compose-up.err}" >&2
  # One known cause deserves naming. Alembic reports a revision it cannot find
  # when the database has been migrated by a branch this checkout does not
  # have — the failure that started #675.
  if grep -q "Can't locate revision identified by" logs/compose-up.err 2>/dev/null; then
    rev="$(sed -n "s/.*Can't locate revision identified by '\([^']*\)'.*/\1/p" \
      logs/compose-up.err | tail -n1)"
    echo "  The database is at revision ${rev:-?}, which does not exist in this checkout." >&2
    echo "  It was migrated by code you do not have — usually a branch that was merged," >&2
    echo "  or one still open elsewhere. Check out the branch carrying that migration" >&2
    echo "  (\`git checkout main && git pull\` if it has landed), then re-run \`make up\`." >&2
  fi
  exit 1
fi
echo "  api + worker + worker-analytics + beat started"

spawn_frontend

# Wait briefly for the API to answer.
printf "→ waiting for API"
api_ok=0
for _ in $(seq 1 "$((API_WAIT_SECONDS))"); do
  if curl -s -m1 http://localhost:8000/health >/dev/null 2>&1; then
    printf " ✓ healthy\n"
    api_ok=1
    break
  fi
  printf "."
  sleep 1
done
if [ "$api_ok" -ne 1 ]; then
  printf "\nAPI did not become healthy. Last API log lines:\n" >&2
  tail -n 40 logs/api.log >&2 || true
  exit 1
fi

printf "→ waiting for dashboard"
frontend_ok=0
frontend_port="$(frontend_listener_port "$(frontend_pid || true)")"
if [ -z "$frontend_port" ]; then
  frontend_port="$FRONTEND_PORT_DEFAULT"
fi
for _ in $(seq 1 "$((FRONTEND_WAIT_SECONDS))"); do
  # Use GET (not HEAD) with a longer timeout because Next dev can take >1s to
  # compile the first request and its HEAD handling may return before the page is
  # actually ready.
  if curl -s -m3 -o /dev/null "http://localhost:${frontend_port}" >/dev/null 2>&1; then
    printf " ✓ ready\n"
    frontend_ok=1
    break
  fi
  printf "."
  sleep 1
done
if [ "$frontend_ok" -ne 1 ]; then
  printf "\nFrontend did not become ready. Last frontend log lines:\n" >&2
  tail -n 40 logs/frontend.log >&2 || true
  exit 1
fi

printf "\nApp is up.\n\nDashboard: http://localhost:%s\nAPI health: http://localhost:8000/health\nLogs: make logs\n\nStop later with: make stop\nFully off later with: make off\n" "$frontend_port"

if [ "$API_BIND" = "127.0.0.1" ]; then
  printf "\nReachable from this machine only. Share it with: make share\n"
else
  # Say plainly what is open and to whom. A share the operator forgets is
  # the failure #928 exists to prevent, so the way back is on the screen.
  printf "\nOpen to this network — anyone on it can use the console, with no password.\n"
  printf "Hand over: %s\n" "${LAN_SHARE_URL:-http://$(hostname):$frontend_port}"
  printf "Close it again with: make up\n"
fi
