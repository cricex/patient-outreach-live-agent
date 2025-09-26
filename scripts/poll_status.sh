#!/usr/bin/env bash
# poll_status.sh — poll $APP_BASE_URL/status every X seconds, log to ./status/poll.log,
# truncate the log on each run, pretty-print JSON with jq when possible, exit cleanly on Ctrl+C.
# Requires: curl, optional jq
# Usage: poll_status.sh [interval_seconds]

set -euo pipefail

INTERVAL="${1:-5}"

if [[ -z "${APP_BASE_URL:-}" ]]; then
  echo "ERROR: APP_BASE_URL is not set. Example: export APP_BASE_URL='http://localhost:8000'"
  exit 1
fi

URL="${APP_BASE_URL%/}/status"

mkdir -p ../status
: > ../status/poll.log

trap 'echo; echo "Stopping poller..."; exit 0' INT

have_jq=0
if command -v jq >/dev/null 2>&1; then
  have_jq=1
else
  echo "Note: jq not found; logging raw responses. Install jq for pretty JSON formatting." | tee -a ../status/poll.log
  echo
fi

echo "Polling ${URL} every ${INTERVAL}s. Logging to ../status/poll.log"
echo "Press Ctrl+C to stop."
echo

while true; do
  TS="$(date '+%Y-%m-%d %H:%M:%S')"
  hdr="[$TS] GET $URL"
  # Write header to both terminal and log
  echo "$hdr" | tee -a ../status/poll.log

  # Fetch body only; let curl fail the command but not kill the loop
  RESP="$(curl -sS -H 'Accept: application/json' "$URL" 2>&1 || true)"

  if [[ $have_jq -eq 1 ]] && PRETTY="$(printf '%s' "$RESP" | jq -M . 2>/dev/null)"; then
    # Terminal: colorized
    printf "%s\n" "$PRETTY" | jq -C . 1>&2 >/dev/null || true # warm up colorizer (no-op if fails)
    printf "%s\n" "$PRETTY" | jq -C . || true
    # Log: monochrome, no ANSI codes
    printf "%s\n\n" "$PRETTY" >> ../status/poll.log
  else
    # Not JSON or jq missing — show and log raw
    printf "%s\n\n" "$RESP" | tee -a ../status/poll.log
  fi

  sleep "$INTERVAL"
done