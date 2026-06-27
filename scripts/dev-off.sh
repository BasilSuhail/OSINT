#!/usr/bin/env bash
# Quit Docker Desktop after `make stop` has stopped the app. Data is preserved.
set -uo pipefail

if command -v osascript >/dev/null 2>&1; then
  osascript -e 'quit app "Docker"' >/dev/null 2>&1 || true
  echo "Docker Desktop quit requested."
else
  echo "Docker Desktop auto-quit is only supported on macOS. Quit Docker manually."
fi
