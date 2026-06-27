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
for _ in $(seq 1 20); do
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
