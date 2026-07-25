#!/usr/bin/env bash
# Tail the whole stack in one stream (#636).
#
# The backend moved into containers (#634) and stopped writing logs/worker.log,
# so the old `tail -F logs/*.log` showed a frozen file where a live worker used
# to be — a stack that looks dead while it is fine. The backend is read from
# compose, the host-side frontend and ollama from their files, and both go to
# the same terminal.
#
# Ctrl-C stops tailing. It does not stop the stack.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAIL_LINES="${TAIL_LINES:-40}"

# Host-side logs only. The backend labels are deliberately absent: if a stale
# worker.log is still on disk from before #634, tailing it would reintroduce
# exactly the frozen-file confusion this script exists to remove.
HOST_LABELS=(frontend ollama)

started=0
cleanup() {
  # Disarm first: cleanup runs on both INT and EXIT, and without this the INT
  # path re-enters it on the way out and prints the sign-off twice.
  trap - INT TERM EXIT

  # Kill every child rather than tracked pids. `$!` on `tail | while` reports
  # only the last element of the pipeline, so the `tail` survived, and the
  # `wait` this replaces then blocked forever — the sign-off never printed and
  # Ctrl-C appeared to hang.
  pkill -P $$ 2>/dev/null

  # Only when something was actually being tailed: printing "the stack is still
  # running" after "nothing to tail" states the opposite of what just happened.
  [ "$started" -eq 1 ] && printf '\nstopped tailing. The stack is still running.\n'
  return 0
}
trap cleanup INT TERM EXIT

if docker info >/dev/null 2>&1; then
  # `--profile app` so the backend services are matched even though they are
  # profile-gated; without it compose reports "no such service".
  if docker compose --profile app ps --services --status running 2>/dev/null | grep -q .; then
    docker compose --profile app logs -f --tail "$TAIL_LINES" &
    started=1
  else
    echo "(no containers running — start the stack with: make up)"
  fi
else
  echo "(docker unreachable — backend logs unavailable)"
fi

for label in "${HOST_LABELS[@]}"; do
  file="logs/$label.log"
  [ -f "$file" ] || continue
  # `-F` rather than `-f` so a rotated or recreated file is picked up.
  #
  # The label is added by a read loop, not by `sed`, because sed block-buffers
  # when stdout is not a tty: a quiet log's lines sat in a 4 KB buffer and never
  # appeared, which is the same "looks dead, is fine" problem this script exists
  # to fix. `sed -u` would work on GNU but not BSD, and this has to run on macOS
  # and on the Pi.
  tail -n "$TAIL_LINES" -F "$file" 2>/dev/null |
    while IFS= read -r line; do
      printf '%s  | %s\n' "$label" "$line"
    done &

  started=1
done

if [ "$started" -eq 0 ]; then
  echo "Nothing to tail: no containers running and no host logs on disk." >&2
  exit 1
fi

wait
