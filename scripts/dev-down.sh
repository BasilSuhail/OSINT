#!/usr/bin/env bash
# Stop everything started by dev-up.sh: frontend, backend processes, and the
# Docker stores. Data in $OSINT_DATA_DIR is kept.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Ollama is included only via its pidfile, which dev-up.sh writes ONLY when it
# started the server itself — a user-managed `ollama serve` has no pidfile here
# and is left running.
for label in frontend worker worker-analytics beat api ollama; do
  pidfile="logs/$label.pid"
  [ -f "$pidfile" ] || continue
  pid="$(cat "$pidfile")"
  if kill "$pid" 2>/dev/null; then
    echo "stopped $label (pid $pid)"
  else
    echo "$label not running (stale pid $pid)"
  fi
  rm -f "$pidfile"
done

# Also catch any strays started by hand.
for pid in $(lsof -ti tcp:3000 2>/dev/null; lsof -ti tcp:3001 2>/dev/null); do
  if kill "$pid" 2>/dev/null; then
    echo "stopped frontend listener (pid $pid)"
  fi
done
pkill -f "next dev" 2>/dev/null || true
pkill -f "celery -A app.celery_app" 2>/dev/null || true
pkill -f "uvicorn app.api:app" 2>/dev/null || true

echo "→ stopping stores"
if docker info >/dev/null 2>&1; then
  docker compose stop >/dev/null
else
  echo "Docker is not reachable; stores are already stopped or Docker Desktop is closed."
fi
echo "all app processes + stores stopped (data preserved in \$OSINT_DATA_DIR)."
