#!/usr/bin/env bash
# `make clear` — remove regenerable junk, never anything that costs money or
# time to get back.
#
# The distinction that matters: caches you can rebuild in seconds go, caches
# that cost an hour of rate-limited API calls stay. data/backtest_cache is the
# latter — it holds GDELT windows fetched one call per five seconds, and
# deleting it would mean refetching all of them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

human() { du -sh "$1" 2>/dev/null | awk '{print $1}'; }

echo "→ frontend build cache"
if [ -d osint-frontend/.next ]; then
  echo "  removing osint-frontend/.next ($(human osint-frontend/.next))"
  rm -rf osint-frontend/.next
else
  echo "  already clean"
fi

echo "→ python caches"
pycache_count="$(find . -name __pycache__ -type d \
  -not -path './.venv/*' -not -path './node_modules/*' 2>/dev/null | wc -l | tr -d ' ')"
find . -name __pycache__ -type d \
  -not -path './.venv/*' -not -path './node_modules/*' -exec rm -rf {} + 2>/dev/null || true
rm -rf .pytest_cache .ruff_cache
echo "  removed ${pycache_count} __pycache__ dirs, .pytest_cache, .ruff_cache"

echo "→ logs"
if [ -d logs ]; then
  before_logs="$(human logs)"
  # .log, .out and .err are append-only process output. .pid files are NOT
  # touched: dev-down.sh reads them to stop running services, and removing one
  # would orphan whatever it points at.
  find logs -type f \( -name '*.log' -o -name '*.out' -o -name '*.err' \) \
    -exec sh -c ': > "$1"' _ {} \; 2>/dev/null || true
  echo "  truncated log/out/err in logs/ (${before_logs} -> $(human logs)); .pid files kept"
else
  echo "  no logs directory"
fi

echo "→ docker"
if docker info >/dev/null 2>&1; then
  before="$(docker system df --format '{{.Type}} {{.Reclaimable}}' 2>/dev/null | tr '\n' '; ')"
  docker container prune -f >/dev/null 2>&1 || true
  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -f >/dev/null 2>&1 || true
  echo "  pruned stopped containers, dangling images, build cache"
  echo "  was: ${before}"
  docker system df 2>/dev/null | tail -n +2 | sed 's/^/  /'
else
  echo "  docker not reachable; skipped"
fi

cat <<'EOF'

Left alone on purpose:
  data/                  Postgres, Redis, exports — your actual data
  data/backtest_cache/   GDELT windows; refetching costs an hour of rate limits
  backups/               database dumps
  .env                   credentials
EOF
