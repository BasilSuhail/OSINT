#!/usr/bin/env bash
# Clean local dev runtime debris without touching data, secrets, or databases.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

in_this_repo() {
  local pid="$1"
  local cwd
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  [ "$cwd" = "$ROOT" ] || [ "$cwd" = "$ROOT/osint-frontend" ]
}

kill_matches() {
  local label="$1"
  local pattern="$2"
  local pids
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    echo "no stale $label processes"
    return
  fi
  while read -r pid; do
    [ -n "$pid" ] || continue
    if ! in_this_repo "$pid"; then
      continue
    fi
    if kill "$pid" 2>/dev/null; then
      echo "stopped stale $label process (pid $pid)"
    fi
  done <<<"$pids"
}

kill_matches "Next build" "osint-frontend/.*/next.* build|osint-frontend/node_modules/.bin/.*/next build|node .*pnpm build"
kill_matches "Next dev" "osint-frontend/.*/next.* dev|next-server \\(v"
kill_matches "frontend shell" "cd osint-frontend && pnpm dev"

if [ -d osint-frontend/.next ]; then
  rm -rf osint-frontend/.next
  echo "removed osint-frontend/.next"
else
  echo "no osint-frontend/.next cache"
fi

if [ -d logs ]; then
  find logs -name '*.pid' -type f -print | while read -r pidfile; do
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pidfile"
      echo "removed stale $pidfile"
    fi
  done
else
  echo "no logs directory"
fi

echo "dev cleanup complete"
