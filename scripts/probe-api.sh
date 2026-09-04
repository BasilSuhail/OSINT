#!/usr/bin/env bash
#: Prove the API through the host port Docker actually published.
#:
#: The container health check reaches localhost inside the container and cannot
#: detect a missing host endpoint. Asking Docker for the mapping also keeps the
#: systemd unit independent of mutable API_PORT configuration in `.env`.
set -u

while true; do
  endpoint="$(docker compose port api 8000 2>/dev/null || true)"
  if [ -n "$endpoint" ] && curl -fsS --max-time 2 "http://$endpoint/health" >/dev/null; then
    exit 0
  fi
  sleep 2
done
