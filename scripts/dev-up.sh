#!/usr/bin/env bash
# Start the whole local stack with one command.
#
# Stores (Postgres + Redis) run in Docker. The three backend processes
# (Celery worker, Celery beat, FastAPI read-API) are started in the BACKGROUND
# with their logs under logs/ and PIDs under logs/*.pid so `make down` can stop
# them. The dashboard (pnpm dev) is the only thing you run yourself, in its own
# terminal, because you usually want to watch it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

echo "→ stores (postgres + redis)"
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

spawn worker .venv/bin/celery -A app.celery_app worker -l info
spawn beat   .venv/bin/celery -A app.celery_app beat   -l info
spawn api    .venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000

# Wait briefly for the API to answer.
printf "→ waiting for API"
for _ in $(seq 1 15); do
  if curl -s -m1 http://localhost:8000/health >/dev/null 2>&1; then
    printf " ✓ healthy\n"; break
  fi
  printf "."; sleep 1
done

cat <<'MSG'

Backend is up. Logs: `make logs` (Ctrl-C to stop tailing — does NOT stop the stack).

Now start the dashboard in THIS terminal:
    cd osint-frontend && pnpm dev      →  http://localhost:3000

Stop everything later with:  make down
MSG
