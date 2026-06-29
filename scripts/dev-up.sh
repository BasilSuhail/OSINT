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

ensure_docker() {
  if docker info >/dev/null 2>&1; then
    return
  fi

  if command -v open >/dev/null 2>&1; then
    echo "→ Docker is not running; opening Docker Desktop"
    open -a Docker >/dev/null 2>&1 || true
  else
    echo "Docker is not running. Start Docker, then run make start again." >&2
    exit 1
  fi

  printf "→ waiting for Docker"
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      printf " ✓ ready\n"
      return
    fi
    printf "."
    sleep 2
  done
  printf "\nDocker did not become ready. Open Docker Desktop, then run make start again.\n" >&2
  exit 1
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

spawn worker .venv/bin/celery -A app.celery_app worker -l info
spawn beat   .venv/bin/celery -A app.celery_app beat   -l info
spawn api    .venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
spawn_frontend

# Wait briefly for the API to answer.
printf "→ waiting for API"
api_ok=0
for _ in $(seq 1 15); do
  if curl -s -m1 http://localhost:8000/health >/dev/null 2>&1; then
    printf " ✓ healthy\n"
    api_ok=1
    break
  fi
  printf "."; sleep 1
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
for _ in $(seq 1 20); do
  if curl -s -m1 -I "http://localhost:${frontend_port}" >/dev/null 2>&1; then
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
