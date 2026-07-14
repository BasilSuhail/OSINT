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

DOCKER_WAIT_SECONDS="${DOCKER_WAIT_SECONDS:-30}"
DOCKER_WAIT_STEP="${DOCKER_WAIT_STEP:-2}"
API_WAIT_SECONDS="${API_WAIT_SECONDS:-20}"
FRONTEND_WAIT_SECONDS="${FRONTEND_WAIT_SECONDS:-60}"
DOCKER_WAIT_MESSAGE_EVERY="${DOCKER_WAIT_MESSAGE_EVERY:-10}"
OLLAMA_WAIT_SECONDS="${OLLAMA_WAIT_SECONDS:-30}"
# Matches settings.brain_model (env BRAIN_MODEL overrides both).
OLLAMA_BRAIN_MODEL="${BRAIN_MODEL:-qwen2.5:1.5b-instruct-q4_K_M}"

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

  # Ensure the light brain model is present (one-time ~1GB pull on a fresh box).
  # Right after `ollama serve` boots, the model listing is briefly flaky — the
  # CLI and the /api/tags endpoint can each momentarily miss a model that IS on
  # disk. Check BOTH and retry for a few seconds so we never trigger a spurious
  # pull for an already-present model. On a genuinely fresh box every check
  # misses and we pull once (the few seconds of waiting are negligible next to
  # the download).
  local have_model=""
  for _ in $(seq 1 8); do
    if ollama list 2>/dev/null | grep -q "$OLLAMA_BRAIN_MODEL" ||
      curl -s -m2 http://localhost:11434/api/tags 2>/dev/null | grep -q "$OLLAMA_BRAIN_MODEL"; then
      have_model=1
      break
    fi
    sleep 1
  done
  if [ -z "$have_model" ]; then
    echo "  pulling brain model $OLLAMA_BRAIN_MODEL (one-time download)…"
    if ! ollama pull "$OLLAMA_BRAIN_MODEL" >logs/ollama-pull.log 2>&1; then
      echo "  model pull failed (see logs/ollama-pull.log); brain stays dormant until pulled."
    fi
  fi
}

FRONTEND_PORT_DEFAULT=3000

frontend_listener_port() {
  local pid="${1:-}"
  if [ -z "$pid" ]; then
    return
  fi

  lsof -Pan -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null | tail -n 1 | sed -n 's/.*TCP .*:\([0-9][0-9]*\) (LISTEN).*/\1/p'
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
compose_up() {
  docker compose up -d "$@" >/dev/null 2>logs/compose-up.err
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

spawn_frontend() {
  local pidfile="logs/frontend.pid"
  local pid
  pid="$(frontend_pid || true)"
  if [ -n "$pid" ]; then
    local port
    port="$(frontend_listener_port "$pid")"
    if [ -z "$port" ]; then
      port="$FRONTEND_PORT_DEFAULT"
    fi
    echo "  frontend already running (pid $pid on :$port)"
    echo "$pid" >"$pidfile"
    return
  fi

  nohup bash -lc "cd osint-frontend && pnpm dev" >"logs/frontend.log" 2>&1 &
  echo $! >"$pidfile"
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

# Two workers (#384, #388). The default queue keeps a tiny concurrent pool
# for the I/O-bound fetchers; every heavy analytical job routes to the
# `analytics` queue consumed at concurrency 1 — strictly one at a time, so
# peak memory is max(one job) and the nightly Ollama batch never overlaps a
# pandas parse. Default to one fetcher locally so Docker, Next, Ollama, and
# Postgres keep enough headroom; fast machines can set CELERY_CONCURRENCY=2.
spawn worker .venv/bin/celery -A app.celery_app worker -l info \
  -Q celery --concurrency "${CELERY_CONCURRENCY:-1}" -n fetchers@%h
spawn worker-analytics .venv/bin/celery -A app.celery_app worker -l info \
  -Q analytics --concurrency 1 -n analytics@%h
spawn beat   .venv/bin/celery -A app.celery_app beat   -l info
spawn api    .venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
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
