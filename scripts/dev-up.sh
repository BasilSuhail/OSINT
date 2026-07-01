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
FRONTEND_WAIT_SECONDS="${FRONTEND_WAIT_SECONDS:-30}"
DOCKER_WAIT_MESSAGE_EVERY="${DOCKER_WAIT_MESSAGE_EVERY:-10}"

docker_ready() {
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

echo "→ stores (postgres + redis)"
ensure_docker
docker compose up -d >/dev/null

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
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "  frontend already running (pid $(cat "$pidfile"))"
    return
  fi

  local port_pid
  port_pid="$(lsof -ti tcp:3000 2>/dev/null | head -n 1 || true)"
  if [ -n "$port_pid" ]; then
    echo "  frontend already listening on :3000 (pid $port_pid)"
    echo "$port_pid" >"$pidfile"
    return
  fi

  nohup bash -lc "cd osint-frontend && pnpm dev" >"logs/frontend.log" 2>&1 &
  echo $! >"$pidfile"
  echo "  frontend started (pid $!) → logs/frontend.log"
}

spawn worker .venv/bin/celery -A app.celery_app worker -l info
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
for _ in $(seq 1 "$((FRONTEND_WAIT_SECONDS))"); do
  if curl -s -m1 -I http://localhost:3000 >/dev/null 2>&1; then
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

cat <<'MSG'

App is up.

Dashboard: http://localhost:3000
API health: http://localhost:8000/health
Logs: make logs

Stop later with: make stop
Fully off later with: make off
MSG
