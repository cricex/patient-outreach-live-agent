#!/usr/bin/env bash
# ngrok_tunnel.sh — launch an HTTP tunnel that forwards to localhost:8000
# Requires: ngrok CLI
# Usage: ./scripts/ngrok_tunnel.sh
set -eu

echo "Starting ngrok tunnel to http://localhost:8000..."
# The following command will run in the foreground until you stop it (Ctrl+C).
# If it fails to start, the script will exit with an error.
ngrok http 8000 --log=stdout --log-level=info

# This part will only be reached if the ngrok command is stopped.
echo "ngrok tunnel stopped."