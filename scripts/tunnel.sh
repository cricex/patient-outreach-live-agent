#!/usr/bin/env bash
# tunnel.sh — manage the devtunnel for local development
# Usage:
#   ./scripts/tunnel.sh start   — kill stale hosts, start tunnel
#   ./scripts/tunnel.sh stop    — kill all devtunnel processes
#   ./scripts/tunnel.sh restart — stop then start
#   ./scripts/tunnel.sh status  — check if tunnel is reachable
set -euo pipefail

TUNNEL_ID="swift-hill-t9dzp4x"
PUBLIC_URL="https://n3st3xsb-8000.usw2.devtunnels.ms"
PORT=8000

_kill() {
  echo "[tunnel] Killing existing devtunnel processes..."
  taskkill //F //IM devtunnel.exe > /dev/null 2>&1 && echo "[tunnel] Killed." || echo "[tunnel] No running processes found."
}

_start() {
  # Verify port config exists
  if ! devtunnel port list "$TUNNEL_ID" 2>/dev/null | grep -q "$PORT"; then
    echo "[tunnel] Port $PORT not configured — creating with protocol http..."
    devtunnel port create "$TUNNEL_ID" -p "$PORT" --protocol http
  fi

  echo "[tunnel] Starting tunnel $TUNNEL_ID..."
  echo "[tunnel] Public URL: $PUBLIC_URL"
  echo "[tunnel] Press Ctrl+C to stop."
  echo ""
  devtunnel host "$TUNNEL_ID"
}

_status() {
  echo "[tunnel] Checking $PUBLIC_URL/status ..."
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$PUBLIC_URL/status" 2>/dev/null || echo "000")
  if [[ "$code" == "200" ]]; then
    echo "[tunnel] OK — tunnel and app are reachable (HTTP $code)"
  elif [[ "$code" == "502" ]]; then
    echo "[tunnel] Bad Gateway — tunnel is up but app is not running on port $PORT"
  elif [[ "$code" == "000" ]]; then
    echo "[tunnel] Unreachable — tunnel is not running"
  else
    echo "[tunnel] Unexpected response: HTTP $code"
  fi
}

case "${1:-}" in
  start)
    _kill
    sleep 1
    _start
    ;;
  stop)
    _kill
    ;;
  restart)
    _kill
    sleep 1
    _start
    ;;
  status)
    _status
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
