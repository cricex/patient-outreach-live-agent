#!/usr/bin/env bash
# load_env.sh — loads variables from a .env file into the current shell.
# To be sourced, not executed directly.
# Usage: . scripts/load_env.sh

set -eu

# The .env file is expected to be in the parent directory of this script's location.
ENV_FILE="$(dirname "$0")/../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Warning: .env file not found at $ENV_FILE. Environment variables will not be loaded." >&2
    exit 0
fi

# Enable automatic export of all variables defined after this point.
set -o allexport

# Source the .env file to load its contents into the current shell environment.
# shellcheck disable=SC1090
source "$ENV_FILE"

# Disable automatic export to avoid affecting subsequent commands in the shell.
set +o allexport