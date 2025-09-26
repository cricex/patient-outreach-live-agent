#!/usr/bin/env bash
# ngrok_auth.sh — configure ngrok with an auth token from .env
# Requires: ngrok CLI, bash, scripts/load_env.sh
# Usage: . ./scripts/load_env.sh && ./scripts/ngrok_auth.sh
set -eu

# Source the environment file to get NGROK_AUTH_TOKEN
# shellcheck disable=SC1091
. "$(dirname "$0")/load_env.sh"

if [ -z "${NGROK_AUTH_TOKEN-}" ]; then
  echo "Error: NGROK_AUTH_TOKEN is not set. Make sure it's in your .env file." >&2
  exit 1
fi

if ngrok config add-authtoken "$NGROK_AUTH_TOKEN"; then
  echo "Successfully configured ngrok authtoken."
else
  echo "Error: Failed to configure ngrok authtoken." >&2
  exit 1
fi