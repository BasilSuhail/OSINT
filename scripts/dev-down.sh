#!/usr/bin/env bash
# Stop everything started by dev-up.sh: the background backend processes
# (worker, beat, api) and the Docker stores. Data in $OSINT_DATA_DIR is kept.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for label in worker beat api; do
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
pkill -f "celery -A app.celery_app" 2>/dev/null || true
pkill -f "uvicorn app.api:app" 2>/dev/null || true

echo "→ stopping stores"
docker compose stop >/dev/null
echo "all backend processes + stores stopped (data preserved in \$OSINT_DATA_DIR)."
